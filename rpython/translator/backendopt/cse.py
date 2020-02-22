""" A very simple common subexpression elimination pass. It's a very simple
forward pass, that simply eliminates operations that were executed in all paths
leading to the current block. Information flows strictly forward, using a cache
of already seen operations. Caches are merged at control flow merges.

No loop invariant code motion occurs (yet). """
import collections

from rpython.translator.backendopt import support
from rpython.rtyper.lltypesystem.lloperation import llop
from rpython.rtyper.lltypesystem import lltype
from rpython.flowspace.model import mkentrymap, Variable, Constant
from rpython.translator.backendopt import removenoops
from rpython.translator import simplify
from rpython.translator.backendopt import ssa, constfold
from rpython.translator.backendopt.writeanalyze import WriteAnalyzer
from rpython.tool.algo import unionfind

from rpython.translator.backendopt.support import log

def has_side_effects(op):
    try:
        return getattr(llop, op.opname).sideeffects
    except AttributeError:
        return True

def common_subexpression_elimination(t, graphs=None):
    if graphs is None:
        graphs = t.graphs
    cse = CSE(t)

    removed_ops = 0
    for graph in graphs:
        removed_ops += cse.transform(graph)
    log.cse("cse removed %s ops" % (removed_ops, ))

def can_fold(op):
    return getattr(llop, op.opname).canfold

class Cache(object):
    def __init__(self, variable_families, analyzer,
                 purecache=None, heapcache=None):
        if purecache is None:
            purecache = {}
        if heapcache is None:
            heapcache = {}
        # (opname, concretetype of result, args) -> previous (life) result
        self.purecache = purecache
        self.heapcache = heapcache
        self.variable_families = variable_families
        self.analyzer = analyzer

    def copy(self):
        return Cache(
                self.variable_families, self.analyzer,
                self.purecache.copy(),
                self.heapcache.copy())

    def _var_rep(self, var):
        # return the representative variable for var. All variables that must
        # be equal to each other always have the same representative. The
        # representative's definition dominates the use of all variables that
        # it represents. casted pointers are considered the same objects.
        # NB: it's very important to use _var_rep only when computing keys in
        # the *cache dictionaries, never to actually put any new variable into
        # the graph, because the concretetypes can change when calling
        # _var_rep.
        if not isinstance(var, Variable):
            return var
        return self.variable_families.find_rep(var)

    def _key_with_replacement(self, key, index, var):
        (opname, concretetype, args) = key
        listargs = list(args)
        listargs[index] = self._var_rep(var)
        return (opname, concretetype, tuple(listargs))

    def _find_new_res(self, results):
        """ merges a list of results into a new variable. If all the results
        are the same, just use that, in which case it's not necessary to pass
        it along any links either. """
        # helper function for _merge_results
        first = self._var_rep(results[0])
        newres = None
        for result in results:
            if newres is None and isinstance(result, Variable):
                # some extra work to get nice var names
                newres = result.copy()
            result = self._var_rep(result)
            if result != first:
                break
        else:
            # all the same!
            return results[0], False
        if newres is None:
            newres = Variable()
            newres.concretetype = results[0].concretetype
        return newres, True

    def _merge_results(self, tuples, results, backedges):
        assert len(results) == len(tuples)
        newres, needs_adding = self._find_new_res(results)
        if not needs_adding:
            return newres
        for linkindex, (link, _) in enumerate(tuples):
            link.args.append(results[linkindex])
        tuples[0][0].target.inputargs.append(newres)
        for backedge in backedges:
            backedge.args.append(newres)
        return newres

    def _merge(self, firstlink, tuples, backedges):
        """ The core algorithm of merging: actually merge many caches. """
        purecache = {}
        block = firstlink.target
        # copy all operations that exist in *all* blocks over.

        # note that a backedge is not a problem for regular pure operations:
        # since the argument is a phi node iff it is not loop invariant,
        # copying things over is always save (yay SSA form!)

        # try non-straight merges: they are merges where the operands are
        # different in the previous blocks, but where the arguments themselves
        # are merged into a new variable in the target block
        # this is code like this:
        # if <cond>
        #     x = i + 1
        #     a = i
        # else:
        #     y = j + 1
        #     a = j
        # here, a + 1 is redundant, and can be replaced by the merge of x and y
        for argindex in range(len(block.inputargs)):
            inputarg = block.inputargs[argindex]
            # bit slow, but probably ok
            firstlinkarg = self._var_rep(firstlink.args[argindex])
            for key, res in self.purecache.iteritems():
                (opname, concretetype, args) = key
                if self._var_rep(args[0]) != firstlinkarg: # XXX other args
                    continue
                results = [res]
                for linkindex, (link, cache) in enumerate(tuples):
                    if linkindex == 0:
                        continue
                    newkey = cache._key_with_replacement(
                            key, 0, link.args[argindex])
                    otherres = cache.purecache.get(newkey, None)
                    if otherres is None:
                        break
                    results.append(otherres)
                else:
                    newkey = self._key_with_replacement(
                            key, 0, inputarg)
                    newres = self._merge_results(tuples, results, backedges)
                    purecache[newkey] = newres

        # the simple case: the operation is really performed on the *same*
        # operands. This is the case if the key exists in all other caches
        for key, res in self.purecache.iteritems():
            results = [res]
            for link, cache in tuples[1:]:
                val = cache.purecache.get(key, None)
                if val is None:
                    break
                results.append(val)
            else:
                newres = self._merge_results(tuples, results, backedges)
                purecache[key] = newres

        # ______________________
        # merge heapcache
        heapcache = {}

        # try non-straight merges
        for argindex in range(len(block.inputargs)):
            inputarg = block.inputargs[argindex]
            # bit slow, but probably ok
            firstlinkarg = self._var_rep(firstlink.args[argindex])
            for key, res in self.heapcache.iteritems():
                (arg, concretetype, fieldname) = key
                if self._var_rep(arg) != firstlinkarg:
                    continue
                results = [res]
                for linkindex, (link, cache) in enumerate(tuples):
                    if linkindex == 0:
                        continue
                    otherarg = cache._var_rep(link.args[argindex])
                    newkey = (otherarg, concretetype, fieldname)
                    otherres = cache.heapcache.get(newkey, None)
                    if otherres is None:
                        break
                    results.append(otherres)
                else:
                    newkey = (self._var_rep(inputarg), concretetype, fieldname)
                    newres = self._merge_results(tuples, results, backedges)
                    heapcache[newkey] = newres

        # regular merge
        for key, res in self.heapcache.iteritems():
            results = [res]
            for link, cache in tuples[1:]:
                val = cache.heapcache.get(key, None)
                if val is None:
                    break
                results.append(val)
            else:
                newres = self._merge_results(tuples, results, backedges)
                heapcache[key] = newres
        return Cache(
                self.variable_families, self.analyzer,
                purecache, heapcache)

    def _clear_heapcache_for(self, concretetype, fieldname):
        for k in self.heapcache.keys():
            if k[1] == concretetype and k[2] == fieldname:
                del self.heapcache[k]

    def _clear_heapcache_for_effects_of_op(self, op):
        if not self.heapcache:
            return
        effects = self.analyzer.analyze(op)
        self._clear_heapcache_for_effects(effects)

    def _clear_heapcache_for_effects(self, effects):
        if self.analyzer.is_top_result(effects):
            self.heapcache.clear()
        else:
            for k in self.heapcache.keys():
                # XXX slow
                key = ('struct', k[1], k[2])
                if key in effects:
                    del self.heapcache[k]

    def _clear_heapcache_for_loop_blocks(self, blocks):
        # XXX use result builder
        effects = self.analyzer.bottom_result()
        for block in blocks:
            for op in block.operations:
                effects = self.analyzer.join_two_results(
                    effects, self.analyzer.analyze(op))
        self._clear_heapcache_for_effects(effects)

    def _replace_with_result(self, op, res):
        assert op.result.concretetype == res.concretetype
        op.opname = 'same_as'
        op.args = [res]
        # now that we know that the variables are the same, just merge them in
        # variable_families too
        self.variable_families.union(res, op.result)

    def cse_block(self, block):
        """ perform common subexpression elimination on block. """
        added_same_as = 0
        for opindex in range(len(block.operations)):
            op = block.operations[opindex]
            # heap operations
            if op.opname == 'getfield':
                fieldname = op.args[1].value
                concretetype = op.args[0].concretetype
                arg0 = self._var_rep(op.args[0])
                key = (arg0, op.args[0].concretetype, fieldname)
                res = self.heapcache.get(key, None)
                if res is not None:
                    self._replace_with_result(op, res)
                    added_same_as += 1
                else:
                    self.heapcache[key] = op.result
                continue
            if op.opname == 'setfield':
                concretetype = op.args[0].concretetype
                target = self._var_rep(op.args[0])
                fieldname = op.args[1].value
                key = (target, concretetype, fieldname)
                res = self.heapcache.get(key, None)
                if (res is not None and
                        self._var_rep(res) ==
                                self._var_rep(op.args[2])):
                    # writing the same value that's already there
                    op.opname = "same_as"
                    op.args = [Constant("not needed setfield", lltype.Void)]
                    added_same_as += 1
                    continue
                self._clear_heapcache_for(concretetype, fieldname)
                self.heapcache[key] = op.args[2]
                continue
            if op.opname == "jit_force_virtualizable":
                T = op.args[0].concretetype
                FIELD = getattr(T.TO, op.args[1].value)
                if hasattr(FIELD, 'TO') and isinstance(FIELD.TO, lltype.GcArray):
                    # clear the cache for the virtualizable array fields, as
                    # they run the risk of being passed around too much
                    self._clear_heapcache_for_effects(
                        {('struct', T, op.args[1].value)})
            if op.opname == "malloc_varsize":
                # we can remember the size of the malloced object
                key = ("getarraysize", lltype.Signed,
                       (self._var_rep(op.result), ))
                self.purecache[key] = op.args[2]

            can_fold_op = can_fold(op)
            has_side_effects_op = has_side_effects(op)
            if can_fold_op:
                key = (op.opname, op.result.concretetype,
                       tuple([self._var_rep(arg) for arg in op.args]))


            if has_side_effects_op:
                self._clear_heapcache_for_effects_of_op(op)

            # foldable operations
            if op.opname == "cast_pointer":
                # cast_pointer is a pretty strange operation! it introduces
                # more aliases, that confuse the CSE pass. Therefore we unify
                # the two variables in variable_families, to improve the
                # folding.
                self.variable_families.union(op.args[0], op.result)
                # don't do anything further
                continue
            if not can_fold_op:
                continue
            res = self.purecache.get(key, None)
            if res is not None:
                self._replace_with_result(op, res)
                added_same_as += 1
            else:
                self.purecache[key] = op.result
        return added_same_as

    @staticmethod
    def merge(tuples, variable_families, analyzer, loop_blocks, backedges):
        """ merge list of
        (incoming link, cache in that link's prevblock)
        tuples into one new cache that holds in the target block.
        """
        if not tuples:
            return Cache(variable_families, analyzer)
        if len(tuples) == 1:
            (link, cache), = tuples
            result = cache.copy()
        else:
            firstlink, firstcache = tuples[0]
            result = firstcache._merge(firstlink, tuples, backedges)
        if loop_blocks:
            # for all blocks in the loop, clean the heapcache for their effects
            # that way, loop-invariant reads can be removed, if no one writes to
            # anything that can alias with them.
            result._clear_heapcache_for_loop_blocks(loop_blocks)
        return result

def compute_reachability_no_backedges(graph, backedges):
    reachable = {}
    blocks = list(graph.iterblocks())
    # Reversed order should make the reuse path more likely.
    for block in reversed(blocks):
        reach = set()
        scheduled = [block]
        while scheduled:
            current = scheduled.pop()
            for link in current.exits:
                if link in backedges:
                    continue
                if link.target in reachable:
                    reach.add(link.target)
                    reach = reach | reachable[link.target]
                    continue
                if link.target not in reach:
                    reach.add(link.target)
                    scheduled.append(link.target)
        reachable[block] = reach
    return reachable

def loop_blocks(graph, backedges, entrymap):
    reachable_no_backedges = compute_reachability_no_backedges(graph, backedges)
    reachable = support.compute_reachability(graph)
    result = {}
    for block in graph.iterblocks():
        entering_backedges = [link for link in entrymap[block]
                if link in backedges]
        if not entering_backedges:
            # no backedge entries
            continue
        loop_blocks = {block}
        for target in reachable_no_backedges[block]:
            if any(link.prevblock in reachable[target]
                       for link in entering_backedges):
                loop_blocks.add(target)
        result[block] = loop_blocks
    return result

class CSE(object):
    def __init__(self, translator):
        self.translator = translator
        self.analyzer = WriteAnalyzer(translator)

    def transform(self, graph):
        """ Perform CSE on graph. """
        # this optimization really works on SSA graphs. don't transform the
        # graph, but use the data flow analysis of SSA to figure out which SSI
        # variables would be the same SSA variable
        variable_families = ssa.DataFlowFamilyBuilder(graph).get_variable_families()
        entrymap = mkentrymap(graph)
        backedges = support.find_backedges(graph)
        loops = loop_blocks(graph, backedges, entrymap)
        todo = collections.deque([graph.startblock])

        # map blocks to a list of
        # (incoming link, cache in that link's prevblock)
        caches_to_merge = collections.defaultdict(list)
        done = set()
        enqueued = {graph.startblock}

        added_same_as = 0

        while todo:
            block = todo.popleft()
            assert block not in done

            current_backedges = [link for link in entrymap[block]
                                    if link in backedges]

            if not block.is_final_block():
                cache = Cache.merge(
                    caches_to_merge[block], variable_families, self.analyzer,
                    loops.get(block, None), current_backedges)
                added_same_as += cache.cse_block(block)
            else:
                cache = None
            done.add(block)
            # add all target blocks where all predecessors are already done,
            # or are backedges
            for exit in block.exits:
                for lnk in entrymap[exit.target]:
                    if lnk.prevblock not in done and lnk not in backedges:
                        break
                else:
                    if exit.target not in done and exit.target not in enqueued:
                        todo.append(exit.target)
                        enqueued.add(exit.target)
                assert cache is not None # final blocks don't have exits
                caches_to_merge[exit.target].append((exit, cache))
        simplify.transform_dead_op_vars(graph)
        if added_same_as:
            ssa.SSA_to_SSI(graph)
            removenoops.remove_same_as(graph)
            constfold.constant_fold_graph(graph) # make use of extra constants
        simplify.transform_dead_op_vars(graph)
        if added_same_as:
            if self.translator.config.translation.verbose:
                log.cse("cse removed %s ops in graph %s" % (added_same_as, graph))
            else:
                log.dot()
        return added_same_as


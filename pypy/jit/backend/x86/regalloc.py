
""" Register allocation scheme. The idea is as follows:
"""

from pypy.jit.metainterp.history import (Box, Const, ConstInt, ConstPtr,
                                         ResOperation, MergePoint, ConstAddr)
from pypy.jit.backend.x86.ri386 import *
from pypy.rpython.lltypesystem import lltype, ll2ctypes, rffi, rstr
from pypy.rlib.objectmodel import we_are_translated
from pypy.rlib.unroll import unrolling_iterable
from pypy.jit.backend.x86 import symbolic

# esi edi and ebp can be added to this list, provided they're correctly
# saved and restored
REGS = [eax, ecx, edx]
WORD = 4
FRAMESIZE = 1024    # XXX should not be a constant at all!!

class TempBox(Box):
    def __init__(self):
        pass

    def __repr__(self):
        return "<TempVar at %s>" % (id(self),)

class PseudoOperation(object):
    def __init__(self, v, from_loc, to_loc):
        self.from_loc = from_loc
        self.to_loc = to_loc
        self.v = v

# pseudo operations for loading/saving reg/mem
class Load(PseudoOperation):
    opname = 'load'

    def __repr__(self):
        return '%s <- %s(%s)' % (self.to_loc, self.v, self.from_loc)

class Store(PseudoOperation):
    opname = 'store'

    def __repr__(self):
        return '%s(%s) -> %s' % (self.v, self.from_loc, self.to_loc)

class Perform(PseudoOperation):
    opname = 'perform'

    def __init__(self, op, arglocs, result_loc):
        self.op = op
        self.result_loc = result_loc
        self.arglocs = arglocs

    def __repr__(self):
        return '%s <- %s(%s)' % (self.result_loc, self.op, self.arglocs)

class PerformDiscard(PseudoOperation):
    opname = 'perform_discard'

    def __init__(self, op, arglocs):
        self.op = op
        self.arglocs = arglocs

    def __repr__(self):
        return '%s(%s)' % (self.op, self.arglocs)

class checkdict(dict):
    def __setitem__(self, key, value):
        assert isinstance(key, Box)
        dict.__setitem__(self, key, value)

def newcheckdict():
    if we_are_translated():
        return {}
    return checkdict()

def convert_to_imm(c):
    if isinstance(c, ConstInt):
        return imm(c.value)
    elif isinstance(c, ConstPtr):
        return imm(rffi.cast(lltype.Signed, c.value))
    elif isinstance(c, ConstAddr):
        return imm(ll2ctypes.cast_adr_to_int(c.value))
    else:
        raise ValueError("convert_to_imm: got a %s" % c)

class RegAlloc(object):
    def __init__(self, operations, guard_op=None):
        # variables that have place in register
        self.reg_bindings = newcheckdict()
        self.stack_bindings = {}
        # compute longevity of variables
        self._compute_vars_longevity(operations)
        self.free_regs = REGS[:]
        self.dirty_stack = {}
        mp = operations[0]
        self.first_merge_point = mp
        jump = operations[-1]
        self.startmp = mp
        if guard_op:
            loop_consts = self._start_from_guard_op(guard_op, mp, jump)
        else:
            loop_consts = self._compute_loop_consts(mp, jump)
        self.current_stack_depth = len(mp.args)
        self.computed_ops = self.walk_operations(operations, loop_consts)
        assert not self.reg_bindings

    def _start_from_guard_op(self, guard_op, mp, jump):
        rev_stack_binds = {}
        self.jump_reg_candidates = {}
        j = 0
        for i in range(len(mp.args)):
            arg = mp.args[i]
            if not isinstance(arg, Const):
                stackpos = guard_op.stacklocs[j]
                loc = guard_op.locs[j]
                if isinstance(loc, REG):
                    self.free_regs = [reg for reg in self.free_regs if reg is not loc]
                    self.reg_bindings[arg] = loc
                    self.dirty_stack[arg] = True
                self.stack_bindings[arg] = stack_pos(stackpos)
                rev_stack_binds[stackpos] = arg
                j += 1
        if jump.opname != 'jump':
            return {}
        for i in range(len(jump.args)):
            argloc = jump.jump_target.arglocs[i]
            jarg = jump.args[i]
            if isinstance(argloc, REG):
                self.jump_reg_candidates[jarg] = argloc
            if (stackpos in rev_stack_binds and
                (self.longevity[rev_stack_binds[stackpos]][1] >
                 self.longevity[jarg][0])):
                # variables cannot occupy the same place on stack, because they
                # overlap.
                pass # we don't care that they occupy the same place
            else:
                #self.dirty_stack[jarg] = True
                # XXX ^^^^^^^^^ why?
                self.stack_bindings[jarg] = stack_pos(i)
        return {}

    def _compute_loop_consts(self, mp, jump):
        self.jump_reg_candidates = {}
        if jump.opname != 'jump':
            loop_consts = {}
        else:
            assert jump.jump_target is mp
            free_regs = REGS[:]
            loop_consts = {}
            for i in range(len(mp.args)):
                if mp.args[i] is jump.args[i]:
                    loop_consts[mp.args[i]] = i
            for i in range(len(mp.args)):
                arg = mp.args[i]
                jarg = jump.args[i]
                if arg is not jarg and not isinstance(jarg, Const):
                    if free_regs:
                        self.jump_reg_candidates[jarg] = free_regs.pop()
                    if self.longevity[arg][1] <= self.longevity[jarg][0]:
                        self.stack_bindings[jarg] = stack_pos(i)
                        self.dirty_stack[jarg] = True
                else:
                    # these are loop consts, but we need stack space anyway
                    self.stack_bindings[jarg] = stack_pos(i)
                    self.dirty_stack[jarg] = True
        return loop_consts

    def _check_invariants(self):
        if not we_are_translated():
            # make sure no duplicates
            assert len(dict.fromkeys(self.reg_bindings.values())) == len(self.reg_bindings)
            # this is not true, due to jump args
            #assert (len(dict.fromkeys([str(i) for i in self.stack_bindings.values()]
            #                          )) == len(self.stack_bindings))
            rev_regs = dict.fromkeys(self.reg_bindings.values())
            for reg in self.free_regs:
                assert reg not in rev_regs
            assert len(rev_regs) + len(self.free_regs) == len(REGS)

    def walk_operations(self, operations, loop_consts):
        # first pass - walk along the operations in order to find
        # load/store places
        new_ops = []
        self.loop_consts = loop_consts
        for i in range(len(operations)):
            op = operations[i]
            if op.opname.startswith('#'):
                continue
            self.position = i
            new_ops += opdict[op.opname](self, op)
            self._check_invariants()
        return new_ops

    def _compute_vars_longevity(self, operations):
        # compute a dictionary that maps variables to index in
        # operations that is a "last-time-seen"
        longevity = {}
        start_live = {}
        for v in operations[0].args:
            start_live[v] = 0
        for i in range(len(operations)):
            op = operations[i]
            if op.results:
                start_live[op.results[0]] = i
            for arg in op.args:
                if isinstance(arg, Box):
                    longevity[arg] = (start_live[arg], i)
            if op.opname.startswith('guard_'):
                for arg in op.liveboxes:
                    if isinstance(arg, Box):
                        longevity[arg] = (start_live[arg], i)
        self.longevity = longevity

    def try_allocate_reg(self, v, selected_reg=None):
        if isinstance(v, Const):
            return convert_to_imm(v)
        if selected_reg is not None:
            res = self.reg_bindings.get(v, None)
            if res:
                if res is selected_reg:
                    return res
                else:
                    del self.reg_bindings[v]
                    self.free_regs.append(res)
            if selected_reg in self.free_regs:
                self.free_regs = [reg for reg in self.free_regs
                                  if reg is not selected_reg]
                self.reg_bindings[v] = selected_reg
                return selected_reg
            return None
        try:
            return self.reg_bindings[v]
        except KeyError:
            if self.free_regs:
                reg = self.jump_reg_candidates.get(v, None)
                if reg:
                    if reg in self.free_regs:
                        self.free_regs = [r for r in self.free_regs if r is not reg]
                        loc = reg
                    else:
                        loc = self.free_regs.pop()
                else:
                    loc = self.free_regs.pop()
                self.reg_bindings[v] = loc
                return loc

    def allocate_new_loc(self, v):
        reg = self.try_allocate_reg(v)
        if reg:
            return reg
        return self.stack_loc(v)

    def return_constant(self, v, forbidden_vars, selected_reg=None,
                        imm_fine=True):
        assert isinstance(v, Const)
        if selected_reg:
            # this means we cannot have it in IMM, eh
            if selected_reg in self.free_regs:
                return selected_reg, [Load(v, convert_to_imm(v), selected_reg)]
            v_to_spill = self.pick_variable_to_spill(v, forbidden_vars, selected_reg)
            if v_to_spill not in self.stack_bindings or v_to_spill in self.dirty_stack:
                newloc = self.stack_loc(v_to_spill)
                try:
                    del self.dirty_stack[v_to_spill]
                except KeyError:
                    pass
                ops = [Store(v_to_spill, selected_reg, newloc)]
            else:
                ops = []
            return selected_reg, ops+[Load(v, convert_to_imm(v), selected_reg)]
        return convert_to_imm(v), []

    def force_allocate_reg(self, v, forbidden_vars, selected_reg=None):
        if isinstance(v, Const):
            return self.return_constant(v, forbidden_vars, selected_reg)
        if isinstance(v, TempBox):
            self.longevity[v] = (self.position, self.position)
        loc = self.try_allocate_reg(v, selected_reg)
        if loc:
            return loc, []
        return self._spill_var(v, forbidden_vars, selected_reg)

    def _spill_var(self, v, forbidden_vars, selected_reg):
        v_to_spill = self.pick_variable_to_spill(v, forbidden_vars, selected_reg)
        loc = self.reg_bindings[v_to_spill]
        del self.reg_bindings[v_to_spill]
        self.reg_bindings[v] = loc
        if v_to_spill not in self.stack_bindings or v_to_spill in self.dirty_stack:
            newloc = self.stack_loc(v_to_spill)
            try:
                del self.dirty_stack[v_to_spill]
            except KeyError:
                pass
            return loc, [Store(v_to_spill, loc, newloc)]
        return loc, []

    def _locs_from_liveboxes(self, guard_op):
        stacklocs = []
        locs = []
        for arg in guard_op.liveboxes:
            if isinstance(arg, Box):
                stacklocs.append(self.stack_loc(arg).position)
                locs.append(self.loc(arg))
        guard_op.stacklocs = stacklocs
        guard_op.locs = locs
        return locs

    def stack_loc(self, v):
        try:
            res = self.stack_bindings[v]
        except KeyError:
            newloc = stack_pos(self.current_stack_depth)
            self.stack_bindings[v] = newloc
            self.current_stack_depth += 1
            res = newloc
        if res.position > FRAMESIZE/WORD:
            raise NotImplementedError("Exceeded FRAME_SIZE")
        return res

    def make_sure_var_in_reg(self, v, forbidden_vars, selected_reg=None,
                             imm_fine=True):
        if isinstance(v, Const):
            return self.return_constant(v, forbidden_vars, selected_reg,
                                        imm_fine)
        prev_loc = self.loc(v)
        loc, ops = self.force_allocate_reg(v, forbidden_vars, selected_reg)
        if prev_loc is loc:
            return loc, []
        return loc, ops + [Load(v, prev_loc, loc)]

    def reallocate_from_to(self, from_v, to_v):
        reg = self.reg_bindings[from_v]
        del self.reg_bindings[from_v]
        self.reg_bindings[to_v] = reg

    def eventually_free_var(self, v):
        if isinstance(v, Const) or v not in self.reg_bindings:
            return
        if self.longevity[v][1] <= self.position:
            self.free_regs.append(self.reg_bindings[v])
            del self.reg_bindings[v]

    def eventually_free_vars(self, vlist):
        for v in vlist:
            self.eventually_free_var(v)

    def loc(self, v):
        if isinstance(v, Const):
            return convert_to_imm(v)
        try:
            return self.reg_bindings[v]
        except KeyError:
            return self.stack_bindings[v]

    def pick_variable_to_spill(self, v, forbidden_vars, selected_reg=None):
        # XXX could be improved
        if v in self.jump_reg_candidates:
            assert selected_reg is None # I don't want to care...
            # now we need to spill a variable that resides in a place where
            # we would like our var to be.
            # XXX Needs test
            # XXX better storage
            for var, reg in self.reg_bindings.items():
                if reg is self.jump_reg_candidates[v] and v not in forbidden_vars:
                    return var
        iter = self.reg_bindings.iterkeys()
        while 1:
            next = iter.next()
            if (next not in forbidden_vars and selected_reg is None or
                self.reg_bindings[next] is selected_reg):
                return next

    def move_variable_away(self, v, prev_loc):
        reg = None
        loc = self.stack_loc(v)
        try:
            del self.dirty_stack[v]
        except KeyError:
            pass
        return Store(v, prev_loc, loc)

    def force_result_in_reg(self, result_v, v, forbidden_vars,
                            selected_reg=None):
        """ Make sure that result is in the same register as v
        and v is copied away if it's further used
        """
        ops = []
        if v in self.reg_bindings and selected_reg:
            _, ops = self.make_sure_var_in_reg(v, forbidden_vars, selected_reg)
        elif v not in self.reg_bindings:
            prev_loc = self.stack_bindings[v]
            loc, o = self.force_allocate_reg(v, forbidden_vars, selected_reg)
            ops += o
            ops.append(Load(v, prev_loc, loc))
        assert v in self.reg_bindings
        if self.longevity[v][1] > self.position:
            # we need to find a new place for variable x and
            # store result in the same place
            loc = self.reg_bindings[v]
            del self.reg_bindings[v]
            if v not in self.stack_bindings or v in self.dirty_stack:
                ops.append(self.move_variable_away(v, loc))
            self.reg_bindings[result_v] = loc
        else:
            self.reallocate_from_to(v, result_v)
            loc = self.reg_bindings[result_v]
        return loc, ops

    def consider_merge_point(self, op):
        # XXX we can sort out here by longevity if we need something
        # more optimal
        ops = [PerformDiscard(op, [])]
        locs = [None] * len(op.args)
        for i in range(len(op.args)):
            arg = op.args[i]
            assert not isinstance(arg, Const)
            reg = None            
            loc = stack_pos(i)
            self.stack_bindings[arg] = loc
            if arg not in self.loop_consts:
                reg = self.try_allocate_reg(arg)
            if reg:
                locs[i] = reg
                self.dirty_stack[arg] = True
            else:
                locs[i] = loc
            # otherwise we have it saved on stack, so no worry
        op.arglocs = locs
        ops[-1].arglocs = op.arglocs
        op.stacklocs = [i for i in range(len(op.args))]
        # XXX be a bit smarter and completely ignore such vars
        self.eventually_free_vars(op.args)
        return ops

    def consider_catch(self, op):
        locs = []
        for arg in op.args:
            l = self.loc(arg)
            if isinstance(l, REG):
                self.dirty_stack[arg] = True
            locs.append(l)
            # possibly constants
        op.arglocs = locs
        op.stacklocs = [self.stack_loc(arg).position for arg in op.args]
        self.eventually_free_vars(op.args)
        return [PerformDiscard(op, [])]

    def consider_guard(self, op):
        loc, ops = self.make_sure_var_in_reg(op.args[0], [])
        locs = self._locs_from_liveboxes(op)
        self.eventually_free_var(op.args[0])
        self.eventually_free_vars(op.liveboxes)
        return ops + [PerformDiscard(op, [loc] + locs)]

    def consider_guard_no_exception(self, op):
        locs = self._locs_from_liveboxes(op)
        self.eventually_free_vars(op.liveboxes)
        return [PerformDiscard(op, locs)]

    consider_guard_true = consider_guard
    consider_guard_false = consider_guard

    #def consider_guard2(self, op):
    #    loc1, ops1 = self.make_sure_var_in_reg(op.args[0], [])
    #    loc2, ops2 = self.make_sure_var_in_reg(op.args[1], [])
    #    locs = [self.loc(arg) for arg in op.liveboxes]
    #    self.eventually_free_vars(op.args + op.liveboxes)
    #    return ops1 + ops2 + [PerformDiscard(op, [loc1, loc2] + locs)]

    #consider_guard_lt = consider_guard2
    #consider_guard_le = consider_guard2
    #consider_guard_eq = consider_guard2
    #consider_guard_ne = consider_guard2
    #consider_guard_gt = consider_guard2
    #consider_guard_ge = consider_guard2
    #consider_guard_is = consider_guard2
    #consider_guard_isnot = consider_guard2

    def consider_guard_value(self, op):
        x = self.loc(op.args[0])
        if not (isinstance(x, REG) or isinstance(op.args[1], Const)):
            x, ops = self.make_sure_var_in_reg(op.args[0], [], imm_fine=False)
        else:
            ops = []
        y = self.loc(op.args[1])
        locs = self._locs_from_liveboxes(op)
        self.eventually_free_vars(op.liveboxes + op.args)
        return ops + [PerformDiscard(op, [x, y] + locs)]

    def consider_guard_class(self, op):
        x, ops = self.make_sure_var_in_reg(op.args[0], [], imm_fine=False)
        y = self.loc(op.args[1])
        locs = self._locs_from_liveboxes(op)
        self.eventually_free_vars(op.liveboxes + op.args)
        return ops + [PerformDiscard(op, [x, y] + locs)]

    def consider_return(self, op):
        if op.args:
            arglocs = [self.loc(op.args[0])]
            self.eventually_free_var(op.args[0])
        else:
            arglocs = []
        return [PerformDiscard(op, arglocs)]
    
    def consider_binop(self, op):
        x = op.args[0]
        ops = []
        if isinstance(x, Const):
            res, ops = self.force_allocate_reg(op.results[0], [])
            argloc = self.loc(op.args[1])
            self.eventually_free_var(op.args[1])
            load_op = Load(x, self.loc(x), res) 
            return ops + [load_op, Perform(op, [res, argloc], res)]
        loc, ops = self.force_result_in_reg(op.results[0], x, op.args)
        argloc = self.loc(op.args[1])
        self.eventually_free_var(op.args[1])
        return ops + [Perform(op, [loc, argloc], loc)]
        # otherwise load this variable to some register

    consider_int_add = consider_binop
    consider_int_mul = consider_binop
    consider_int_sub = consider_binop
    consider_int_and = consider_binop

    def consider_int_neg(self, op):
        res, ops = self.force_result_in_reg(op.results[0], op.args[0], [])
        return ops + [Perform(op, [res], res)]

    consider_bool_not = consider_int_neg

    def consider_int_rshift(self, op):
        tmpvar = TempBox()
        reg, ops = self.force_allocate_reg(tmpvar, [], ecx)
        y = self.loc(op.args[1])
        x, more_ops = self.force_result_in_reg(op.results[0], op.args[0],
                                               op.args + [tmpvar])
        self.eventually_free_vars(op.args + [tmpvar])
        return ops + more_ops + [Perform(op, [x, y, reg], x)]

    def consider_int_mod(self, op):
        l0, ops0 = self.make_sure_var_in_reg(op.args[0], [], eax)
        l1, ops1 = self.make_sure_var_in_reg(op.args[1], [], ecx)
        l2, ops2 = self.force_allocate_reg(op.results[0], [], edx)
        # eax is trashed after that operation
        tmpvar = TempBox()
        _, ops3 = self.force_allocate_reg(tmpvar, [], eax)
        assert (l0, l1, l2) == (eax, ecx, edx)
        self.eventually_free_vars(op.args + [tmpvar])
        return ops0 + ops1 + ops2 + ops3 + [Perform(op, [eax, ecx], edx)]

    def consider_int_floordiv(self, op):
        tmpvar = TempBox()
        l0, ops0 = self.force_result_in_reg(op.results[0], op.args[0], [], eax)
        l1, ops1 = self.make_sure_var_in_reg(op.args[1], [], ecx)
        # we need to make sure edx is empty, since we're going to use it
        l2, ops2 = self.force_allocate_reg(tmpvar, [], edx)
        assert (l0, l1, l2) == (eax, ecx, edx)
        self.eventually_free_vars(op.args + [tmpvar])
        return ops0 + ops1 + ops2 + [Perform(op, [eax, ecx], eax)]

    def consider_compop(self, op):
        vx = op.args[0]
        vy = op.args[1]
        arglocs = [self.loc(vx), self.loc(vy)]
        if (vx in self.reg_bindings or vy in self.reg_bindings or
            isinstance(vx, Const) or isinstance(vy, Const)):
            ops0 = []
        else:
            arglocs[0], ops0 = self.force_allocate_reg(vx, [])
        self.eventually_free_var(vx)
        self.eventually_free_var(vy)
        loc, ops = self.force_allocate_reg(op.results[0], op.args)
        return ops0 + ops + [Perform(op, arglocs, loc)]

    consider_int_lt = consider_compop
    consider_int_gt = consider_compop
    consider_int_ge = consider_compop
    consider_int_le = consider_compop
    consider_char_eq = consider_compop
    consider_int_ne = consider_compop
    consider_int_eq = consider_compop

    def _call(self, op, arglocs, force_store=[]):
        ops = []
        # we need to store all variables which are now in registers
        for v, reg in self.reg_bindings.items():
            if self.longevity[v][1] > self.position or v in force_store:
                ops.append(Store(v, reg, self.stack_loc(v)))
                try:
                    del self.dirty_stack[v]
                except KeyError:
                    pass
        self.reg_bindings = newcheckdict()
        if op.results:
            self.reg_bindings = {op.results[0]: eax}
            self.free_regs = [reg for reg in REGS if reg is not eax]
            return ops + [Perform(op, arglocs, eax)]
        else:
            self.free_regs = REGS[:]
            return ops + [PerformDiscard(op, arglocs)]

    def consider_call_ptr(self, op):
        return self._call(op, [self.loc(arg) for arg in op.args])

    consider_call_void = consider_call_ptr
    consider_call__1 = consider_call_ptr
    consider_call__2 = consider_call_ptr
    consider_call__4 = consider_call_ptr
    consider_call__8 = consider_call_ptr

    def consider_new(self, op):
        return self._call(op, [self.loc(arg) for arg in op.args])

    def consider_new_with_vtable(self, op):
        return self._call(op, [self.loc(arg) for arg in op.args])

    def consider_newstr(self, op):
        ops = self._call(op, [self.loc(arg) for arg in op.args],
                         [op.args[0]])
        loc, ops1 = self.make_sure_var_in_reg(op.args[0], [])
        assert self.loc(op.results[0]) == eax
        # now we have to reload length to some reasonable place
        # XXX hardcoded length offset
        self.eventually_free_var(op.args[0])
        ofs = symbolic.get_field_token(rstr.STR, 'chars')[0]
        res = ops + ops1 + [PerformDiscard(ResOperation('setfield_gc', [], []),
                                           [eax, imm(ofs), loc])]
        return res

    def consider_oononnull(self, op):
        argloc = self.loc(op.args[0])
        self.eventually_free_var(op.args[0])
        reg = self.try_allocate_reg(op.results[0])
        assert reg
        return [Perform(op, [argloc], reg)]

    def consider_setfield_gc(self, op):
        base_loc, ops0  = self.make_sure_var_in_reg(op.args[0], op.args)
        ofs_loc, ops1   = self.make_sure_var_in_reg(op.args[1], op.args)
        value_loc, ops2 = self.make_sure_var_in_reg(op.args[2], op.args)
        self.eventually_free_vars([op.args[0], op.args[1], op.args[2]])
        return (ops0 + ops1 + ops2 +
                [PerformDiscard(op, [base_loc, ofs_loc, value_loc])])

    # XXX location is a bit smaller, but we don't care too much
    consider_strsetitem = consider_setfield_gc

    def consider_getfield_gc(self, op):
        base_loc, ops0 = self.make_sure_var_in_reg(op.args[0], op.args)
        ofs_loc, ops1 = self.make_sure_var_in_reg(op.args[1], op.args)
        self.eventually_free_vars([op.args[0], op.args[1]])
        result_loc, more_ops = self.force_allocate_reg(op.results[0], [])
        return (ops0 + ops1 + more_ops +
                [Perform(op, [base_loc, ofs_loc], result_loc)])

    consider_getfield_raw = consider_getfield_gc
    consider_getfield_raw = consider_getfield_gc

    def consider_getitem(self, op):
        return self._call(op, [self.loc(arg) for arg in op.args])

    def consider_zero_gc_pointers_inside(self, op):
        self.eventually_free_var(op.args[0])
        return []

    def consider_same_as(self, op):
        x = op.args[0]
        if isinstance(x, Const):
            pos = self.allocate_new_loc(op.results[0])
            return [Load(op.results[0], self.loc(x), pos)]
        if self.longevity[x][1] > self.position or x not in self.reg_bindings:
            if x in self.reg_bindings:
                res = self.allocate_new_loc(op.results[0])
                return [Load(op.results[0], self.loc(x), res)]
            else:
                res, ops = self.force_allocate_reg(op.results[0], op.args)
                return ops + [Load(op.results[0], self.loc(x), res)]
        else:
            self.reallocate_from_to(x, op.results[0])
            return []

    consider_cast_int_to_char = consider_same_as
    consider_cast_int_to_ptr  = consider_same_as

    def consider_int_is_true(self, op):
        argloc, ops = self.force_allocate_reg(op.args[0], [])
        self.eventually_free_var(op.args[0])
        resloc, more_ops = self.force_allocate_reg(op.results[0], [])
        return ops + more_ops + [Perform(op, [argloc], resloc)]

    def consider_nullity(self, op):
        # doesn't need a register in arg
        argloc = self.loc(op.args[0])
        self.eventually_free_var(op.args[0])
        resloc, ops = self.force_allocate_reg(op.results[0], [])
        return ops + [Perform(op, [argloc], resloc)]
    
    consider_ooisnull = consider_nullity
    consider_oononnull = consider_nullity

    def consider_strlen(self, op):
        base_loc, ops0 = self.make_sure_var_in_reg(op.args[0], op.args)
        self.eventually_free_var(op.args[0])
        result_loc, more_ops = self.force_allocate_reg(op.results[0], [])
        return ops0 + more_ops + [Perform(op, [base_loc], result_loc)]

    def consider_strgetitem(self, op):
        base_loc, ops0 = self.make_sure_var_in_reg(op.args[0], op.args)
        ofs_loc, ops1 = self.make_sure_var_in_reg(op.args[1], op.args)
        self.eventually_free_vars([op.args[0], op.args[1]])
        result_loc, more_ops = self.force_allocate_reg(op.results[0], [])
        return (ops0 + ops1 + more_ops +
                [Perform(op, [base_loc, ofs_loc], result_loc)])

    def consider_jump(self, op):
        ops = []
        laterops = []
        for i in range(len(op.args)):
            arg = op.args[i]
            if not (isinstance(arg, Const) or (arg in self.loop_consts
                                               and self.loop_consts[arg] == i)):
                mp = op.jump_target
                assert isinstance(mp, MergePoint)
                res = mp.arglocs[i]
                if arg in self.reg_bindings:
                    if not isinstance(res, REG):
                        ops.append(Store(arg, self.loc(arg), self.stack_bindings[arg]))
                    elif res is self.reg_bindings[arg]:
                        pass
                    else:
                        # register, but wrong
                        # we're going to need it (otherwise it'll be dead), so
                        # we spill it and reload
                        # if our register is free, easy
                        for v, reg in self.reg_bindings.items():
                            if reg is res:
                                ops.append(Store(arg, self.loc(arg), self.stack_loc(arg)))
                                laterops.append(Load(arg, self.stack_loc(arg), res))
                                break
                        else:
                            ops.append(Load(arg, self.loc(arg), res))
                else:
                    assert arg in self.stack_bindings
                    if isinstance(res, REG):
                        laterops.append(Load(arg, self.loc(arg), res))
                    else:
                        # otherwise it's correct
                        if not we_are_translated():
                            assert repr(self.stack_bindings[arg]) == repr(res)
                            assert arg not in self.dirty_stack
        self.eventually_free_vars(op.args)
        return ops + laterops + [PerformDiscard(op, [])]

    def consider_debug_assert(self, op):
        # ignore
        self.eventually_free_var(op.args[0])
        return []

opdict = {}

for name, value in RegAlloc.__dict__.iteritems():
    if name.startswith('consider_'):
        opname = name[len('consider_'):]
        opdict[opname] = value

def arg_pos(i):
    res = mem(esp, FRAMESIZE + WORD * (i + 1))
    res.position = (i + 1) + FRAMESIZE // WORD
    return res

def stack_pos(i):
    res = mem(esp, WORD * i)
    res.position = i
    return res

def lower_byte(reg):
    # argh
    if reg is eax:
        return al
    elif reg is ebx:
        return bl
    elif reg is ecx:
        return cl
    elif reg is edx:
        return dl
    else:
        raise NotImplementedError()

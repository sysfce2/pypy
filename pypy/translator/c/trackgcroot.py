#! /usr/bin/env python

import re, sys, os

r_functionstart = re.compile(r"\t.type\s+(\w+),\s*[@]function\s*$")
r_functionend   = re.compile(r"\t.size\s+(\w+),\s*[.]-(\w+)\s*$")
r_label         = re.compile(r"([.]?\w+)[:]\s*$")
r_globl         = re.compile(r"\t[.]globl\t(\w+)\s*$")
r_insn          = re.compile(r"\t([a-z]\w*)\s")
r_jump          = re.compile(r"\tj\w+\s+([.]?\w+)\s*$")
OPERAND         =            r"[-\w$%+.:@]+(?:[(][\w%,]+[)])?|[(][\w%,]+[)]"
r_unaryinsn     = re.compile(r"\t[a-z]\w*\s+("+OPERAND+")\s*$")
r_unaryinsn_star= re.compile(r"\t[a-z]\w*\s+([*]"+OPERAND+")\s*$")
r_jmp_switch    = re.compile(r"\tjmp\t[*]([.]?\w+)[(]")
r_jmptable_item = re.compile(r"\t.long\t([.]?\w+)\s*$")
r_jmptable_end  = re.compile(r"\t.text|\t.section\s+.text")
r_binaryinsn    = re.compile(r"\t[a-z]\w*\s+("+OPERAND+"),\s*("+OPERAND+")\s*$")
LOCALVAR        = r"%eax|%edx|%ecx|%ebx|%esi|%edi|%ebp|\d*[(]%esp[)]"
LOCALVARFP      = LOCALVAR + r"|-?\d*[(]%ebp[)]"
r_gcroot_marker = re.compile(r"\t/[*] GCROOT ("+LOCALVARFP+") [*]/")
r_localvarnofp  = re.compile(LOCALVAR)
r_localvarfp    = re.compile(LOCALVARFP)
r_localvar_esp  = re.compile(r"(\d*)[(]%esp[)]")
r_localvar_ebp  = re.compile(r"(-?\d*)[(]%ebp[)]")


class GcRootTracker(object):

    def __init__(self, verbose=0):
        self.gcmaptable = []
        self.verbose = verbose
        self.seen_main = False

    def dump(self, output):
        assert self.seen_main
        shapes = {}
        print >> output, """\t.text
        .globl pypy_asm_stackwalk
            .type pypy_asm_stackwalk, @function
        pypy_asm_stackwalk:
            /* See description in asmgcroot.py */
            movl   4(%esp), %edx     /* my argument, which is the callback */
            movl   %esp, %eax        /* my frame top address */
            pushl  %eax              /* ASM_FRAMEDATA[4] */
            pushl  %ebp              /* ASM_FRAMEDATA[3] */
            pushl  %edi              /* ASM_FRAMEDATA[2] */
            pushl  %esi              /* ASM_FRAMEDATA[1] */
            pushl  %ebx              /* ASM_FRAMEDATA[0] */
            movl   %esp, %eax        /* address of ASM_FRAMEDATA */
            pushl  %eax
            call   *%edx             /* invoke the callback */
            popl   %eax
            popl   %ebx              /* restore from ASM_FRAMEDATA[0] */
            popl   %esi              /* restore from ASM_FRAMEDATA[1] */
            popl   %edi              /* restore from ASM_FRAMEDATA[2] */
            popl   %ebp              /* restore from ASM_FRAMEDATA[3] */
            popl   %eax
            ret
        .size pypy_asm_stackwalk_init, .-pypy_asm_stackwalk_init
        """
        print >> output, '\t.data'
        print >> output, '\t.align\t4'
        print >> output, '\t.globl\t__gcmapstart'
        print >> output, '__gcmapstart:'
        for label, state in self.gcmaptable:
            if state not in shapes:
                lst = ['__gcmap_shape']
                for n in state:
                    if n < 0:
                        n = 'm%d' % (-n,)
                    lst.append(str(n))
                shapes[state] = '_'.join(lst)
            print >> output, '\t.long\t%s' % (label,)
            print >> output, '\t.long\t%s' % (shapes[state],)
        print >> output, '\t.globl\t__gcmapend'
        print >> output, '__gcmapend:'
        print >> output, '\t.section\t.rodata'
        print >> output, '\t.align\t4'
        keys = shapes.keys()
        keys.sort()
        FIXED = 1 + len(CALLEE_SAVE_REGISTERS)
        for state in keys:
            print >> output, '%s:' % (shapes[state],)
            for i in range(FIXED):
                print >> output, '\t.long\t%d' % (state[i],)
            print >> output, '\t.long\t%d' % (len(state)-FIXED,)
            for p in state[FIXED:]:
                print >> output, '\t.long\t%d' % (p,)         # gcroots

    def process(self, iterlines, newfile, entrypoint='main', filename='?'):
        functionlines = None
        for line in iterlines:
            if r_functionstart.match(line):
                assert functionlines is None, (
                    "missed the end of the previous function")
                functionlines = []
            if functionlines is not None:
                functionlines.append(line)
            else:
                newfile.write(line)
            if r_functionend.match(line):
                assert functionlines is not None, (
                    "missed the start of the current function")
                self.process_function(functionlines, newfile, entrypoint,
                                      filename)
                functionlines = None

    def process_function(self, lines, newfile, entrypoint, filename):
        tracker = FunctionGcRootTracker(lines)
        tracker.is_main = tracker.funcname == entrypoint
        if self.verbose:
            print >> sys.stderr, '[trackgcroot:%s] %s' % (filename,
                                                          tracker.funcname)
        table = tracker.computegcmaptable(self.verbose)
        if self.verbose > 1:
            for label, state in table:
                print >> sys.stderr, label, '\t', state
        if tracker.is_main:
            fp = tracker.uses_frame_pointer
            table = self.fixup_entrypoint_table(table, fp)
        self.gcmaptable.extend(table)
        newfile.writelines(tracker.lines)

    def fixup_entrypoint_table(self, table, uses_frame_pointer):
        self.seen_main = True
        # as an end marker, set the CALLEE_SAVE_REGISTERS locations to -1.
        # this info is not useful because we don't go to main()'s caller.
        newtable = []
        MARKERS = (-1, -1, -1, -1)
        for label, shape in table:
            newtable.append((label, shape[:1] + MARKERS + shape[5:]))
        table = newtable

        if uses_frame_pointer:
            # the main() function may contain strange code that aligns the
            # stack pointer to a multiple of 16, which messes up our framesize
            # computation.  So just for this function, we use a frame size
            # of 0 to ask asmgcroot to read %ebp to find the frame pointer.
            newtable = []
            for label, shape in table:
                newtable.append((label, (0,) + shape[1:]))
            table = newtable
        return table


class FunctionGcRootTracker(object):

    def __init__(self, lines):
        match = r_functionstart.match(lines[0])
        self.funcname = match.group(1)
        match = r_functionend.match(lines[-1])
        assert self.funcname == match.group(1)
        assert self.funcname == match.group(2)
        self.lines = lines
        self.uses_frame_pointer = False
        self.r_localvar = r_localvarnofp
        self.is_main = False

    def computegcmaptable(self, verbose=0):
        self.findlabels()
        self.parse_instructions()
        try:
            if not self.list_call_insns():
                return []
            self.findprevinsns()
            self.findframesize()
            self.fixlocalvars()
            self.trackgcroots()
            self.extend_calls_with_labels()
        finally:
            if verbose > 2:
                self.dump()
        return self.gettable()

    def gettable(self):
        """Returns a list [(label_after_call, shape_tuple)]
        where shape_tuple = (framesize, where_is_ebx_saved, ...
                            ..., where_is_ebp_saved, gcroot0, gcroot1...)
        """
        table = []
        for insn in self.list_call_insns():
            if not hasattr(insn, 'framesize'):
                continue     # calls that never end up reaching a RET
            shape = [insn.framesize + 4]     # accounts for the return address
            # the first gcroots are always the ones corresponding to
            # the callee-saved registers
            for reg in CALLEE_SAVE_REGISTERS:
                shape.append(None)
            for loc, tag in insn.gcroots.items():
                if not isinstance(loc, int):
                    # a special representation for a register location,
                    # as an odd-valued number
                    loc = CALLEE_SAVE_REGISTERS.index(loc) * 2 + 1
                if tag is None:
                    shape.append(loc)
                else:
                    regindex = CALLEE_SAVE_REGISTERS.index(tag)
                    shape[1 + regindex] = loc
            if None in shape:
                reg = CALLEE_SAVE_REGISTERS[shape.index(None) - 1]
                raise AssertionError("cannot track where register %s is saved"
                                     % (reg,))
            table.append((insn.global_label, tuple(shape)))
        return table

    def findlabels(self):
        self.labels = {}      # {name: Label()}
        for lineno, line in enumerate(self.lines):
            match = r_label.match(line)
            if match:
                label = match.group(1)
                assert label not in self.labels, "duplicate label"
                self.labels[label] = Label(label, lineno)

    def parse_instructions(self):
        self.insns = [InsnFunctionStart()]
        in_APP = False
        for lineno, line in enumerate(self.lines):
            self.currentlineno = lineno
            insn = []
            match = r_insn.match(line)
            if match:
                if not in_APP:
                    opname = match.group(1)
                    try:
                        meth = getattr(self, 'visit_' + opname)
                    except AttributeError:
                        meth = self.find_missing_visit_method(opname)
                    insn = meth(line)
            elif r_gcroot_marker.match(line):
                insn = self._visit_gcroot_marker(line)
            elif line == '#APP\n':
                in_APP = True
            elif line == '#NO_APP\n':
                in_APP = False
            else:
                match = r_label.match(line)
                if match:
                    insn = self.labels[match.group(1)]
            if isinstance(insn, list):
                self.insns.extend(insn)
            else:
                self.insns.append(insn)
            del self.currentlineno

    def find_missing_visit_method(self, opname):
        # only for operations that are no-ops as far as we are concerned
        prefix = opname
        while prefix not in self.IGNORE_OPS_WITH_PREFIXES:
            prefix = prefix[:-1]
            if not prefix:
                raise UnrecognizedOperation(opname)
        visit_nop = FunctionGcRootTracker.__dict__['visit_nop']
        setattr(FunctionGcRootTracker, 'visit_' + opname, visit_nop)
        return self.visit_nop

    def findprevinsns(self):
        # builds the previous_insns of each Insn.  For Labels, all jumps
        # to them are already registered; all that is left to do is to
        # make each Insn point to the Insn just before it.
        for i in range(len(self.insns)-1):
            previnsn = self.insns[i]
            nextinsn = self.insns[i+1]
            try:
                lst = nextinsn.previous_insns
            except AttributeError:
                lst = nextinsn.previous_insns = []
            if not isinstance(previnsn, InsnStop):
                lst.append(previnsn)

    def list_call_insns(self):
        return [insn for insn in self.insns if isinstance(insn, InsnCall)]

    def findframesize(self):

        def walker(insn, size_delta):
            check = deltas.setdefault(insn, size_delta)
            assert check == size_delta, (
                "inconsistent frame size at instruction %s" % (insn,))
            if isinstance(insn, InsnStackAdjust):
                size_delta -= insn.delta
            if not hasattr(insn, 'framesize'):
                yield size_delta   # continue walking backwards

        for insn in self.insns:
            if isinstance(insn, (InsnRet, InsnEpilogue, InsnGCROOT)):
                deltas = {}
                self.walk_instructions_backwards(walker, insn, 0)
                size_at_insn = []
                for insn1, delta1 in deltas.items():
                    if hasattr(insn1, 'framesize'):
                        size_at_insn.append(insn1.framesize + delta1)
                assert len(size_at_insn) > 0, (
                    "cannot reach the start of the function??")
                size_at_insn = size_at_insn[0]
                for insn1, delta1 in deltas.items():
                    size_at_insn1 = size_at_insn - delta1
                    if hasattr(insn1, 'framesize'):
                        assert insn1.framesize == size_at_insn1, (
                            "inconsistent frame size at instruction %s" %
                            (insn1,))
                    else:
                        insn1.framesize = size_at_insn1

    def fixlocalvars(self):
        for insn in self.insns:
            if hasattr(insn, 'framesize'):
                for name in insn._locals_:
                    localvar = getattr(insn, name)
                    match = r_localvar_esp.match(localvar)
                    if match:
                        ofs_from_esp = int(match.group(1) or '0')
                        localvar = ofs_from_esp - insn.framesize
                        assert localvar != 0    # that's the return address
                        setattr(insn, name, localvar)
                    elif self.uses_frame_pointer:
                        match = r_localvar_ebp.match(localvar)
                        if match:
                            ofs_from_ebp = int(match.group(1) or '0')
                            localvar = ofs_from_ebp - 4
                            assert localvar != 0    # that's the return address
                            setattr(insn, name, localvar)

    def trackgcroots(self):

        def walker(insn, loc):
            source = insn.source_of(loc, tag)
            if source is somenewvalue:
                pass   # done
            else:
                yield source

        for insn in self.insns:
            for loc, tag in insn.requestgcroots().items():
                self.walk_instructions_backwards(walker, insn, loc)

    def dump(self):
        for insn in self.insns:
            size = getattr(insn, 'framesize', '?')
            print '%4s  %s' % (size, insn)

    def walk_instructions_backwards(self, walker, initial_insn, initial_state):
        pending = []
        seen = {}
        def schedule(insn, state):
            for previnsn in insn.previous_insns:
                key = previnsn, state
                if key not in seen:
                    seen[key] = True
                    pending.append(key)
        schedule(initial_insn, initial_state)
        while pending:
            insn, state = pending.pop()
            for prevstate in walker(insn, state):
                schedule(insn, prevstate)

    def extend_calls_with_labels(self):
        # walk backwards, because inserting the global labels in self.lines
        # is going to invalidate the lineno of all the InsnCall objects
        # after the current one.
        for call in self.list_call_insns()[::-1]:
            if hasattr(call, 'framesize'):
                self.create_global_label(call)

    def create_global_label(self, call):
        # we need a globally-declared label just after the call.
        # Reuse one if it is already there (e.g. from a previous run of this
        # script); otherwise invent a name and add the label to tracker.lines.
        label = None
        # this checks for a ".globl NAME" followed by "NAME:"
        match = r_globl.match(self.lines[call.lineno+1])
        if match:
            label1 = match.group(1)
            match = r_label.match(self.lines[call.lineno+2])
            if match:
                label2 = match.group(1)
                if label1 == label2:
                    label = label2
        if label is None:
            k = call.lineno
            while 1:
                label = '__gcmap_IN_%s_%d' % (self.funcname, k)
                if label not in self.labels:
                    break
                k += 1
            self.labels[label] = None
            self.lines.insert(call.lineno+1, '%s:\n' % (label,))
            self.lines.insert(call.lineno+1, '\t.globl\t%s\n' % (label,))
        call.global_label = label

    # ____________________________________________________________

    def _visit_gcroot_marker(self, line):
        match = r_gcroot_marker.match(line)
        loc = match.group(1)
        return InsnGCROOT(loc)

    def visit_nop(self, line):
        return []

    IGNORE_OPS_WITH_PREFIXES = dict.fromkeys([
        'cmp', 'test', 'set', 'sahf', 'cltd', 'cld', 'std',
        'rep', 'movs', 'lods', 'stos', 'scas',
        # floating-point operations cannot produce GC pointers
        'f',
        # arithmetic operations should not produce GC pointers
        'inc', 'dec', 'not', 'neg', 'or', 'and', 'sbb', 'adc',
        'shl', 'shr', 'sal', 'sar', 'rol', 'ror', 'mul', 'imul', 'div', 'idiv',
        # zero-extending moves should not produce GC pointers
        'movz',
        ])

    visit_movb = visit_nop
    visit_movw = visit_nop
    visit_addb = visit_nop
    visit_addw = visit_nop
    visit_subb = visit_nop
    visit_subw = visit_nop
    visit_xorb = visit_nop
    visit_xorw = visit_nop

    def visit_addl(self, line, sign=+1):
        match = r_binaryinsn.match(line)
        target = match.group(2)
        if target == '%esp':
            count = match.group(1)
            assert count.startswith('$')
            return InsnStackAdjust(sign * int(count[1:]))
        elif self.r_localvar.match(target):
            return InsnSetLocal(target)
        else:
            return []

    def visit_subl(self, line):
        return self.visit_addl(line, sign=-1)

    def unary_insn(self, line):
        match = r_unaryinsn.match(line)
        target = match.group(1)
        if self.r_localvar.match(target):
            return InsnSetLocal(target)
        else:
            return []

    def binary_insn(self, line):
        match = r_binaryinsn.match(line)
        if not match:
            raise UnrecognizedOperation(line)
        target = match.group(2)
        if self.r_localvar.match(target):
            return InsnSetLocal(target)
        elif target == '%esp':
            raise UnrecognizedOperation(line)
        else:
            return []

    visit_xorl = binary_insn   # used in "xor reg, reg" to create a NULL GC ptr
    visit_orl = binary_insn

    def visit_andl(self, line):
        match = r_binaryinsn.match(line)
        target = match.group(2)
        if target == '%esp':
            # only for  andl $-16, %esp  used to align the stack in main().
            # If gcc compiled main() with a frame pointer, then it should use
            # %ebp-relative addressing and not %esp-relative addressing
            # and asmgcroot will read %ebp to find the frame.  If main()
            # is compiled without a frame pointer, the total frame size that
            # we compute ends up being bogus but that's ok because gcc has
            # to use %esp-relative addressing only and we don't need to walk
            # to caller frames because it's main().
            assert self.is_main
            return []
        else:
            return self.binary_insn(line)

    def visit_leal(self, line):
        match = r_binaryinsn.match(line)
        target = match.group(2)
        if target == '%esp':
            # only for  leal -12(%ebp), %esp  in function epilogues
            source = match.group(1)
            match = r_localvar_ebp.match(source)
            if not match:
                framesize = None    # strange instruction
            else:
                ofs_from_ebp = int(match.group(1) or '0')
                assert ofs_from_ebp < 0
                framesize = 4 - ofs_from_ebp
            return InsnEpilogue(framesize)
        else:
            return self.binary_insn(line)

    def insns_for_copy(self, source, target):
        if source == '%esp' or target == '%esp':
            raise UnrecognizedOperation('%s -> %s' % (source, target))
        elif self.r_localvar.match(target):
            if self.r_localvar.match(source):
                return [InsnCopyLocal(source, target)]
            else:
                return [InsnSetLocal(target)]
        else:
            return []

    def visit_movl(self, line):
        match = r_binaryinsn.match(line)
        source = match.group(1)
        target = match.group(2)
        if source == '%esp' and target == '%ebp':
            return self._visit_prologue()
        elif source == '%ebp' and target == '%esp':
            return self._visit_epilogue()
        return self.insns_for_copy(source, target)

    def visit_pushl(self, line):
        match = r_unaryinsn.match(line)
        source = match.group(1)
        return [InsnStackAdjust(-4)] + self.insns_for_copy(source, '(%esp)')

    def _visit_pop(self, target):
        return self.insns_for_copy('(%esp)', target) + [InsnStackAdjust(+4)]

    def visit_popl(self, line):
        match = r_unaryinsn.match(line)
        target = match.group(1)
        return self._visit_pop(target)

    def _visit_prologue(self):
        # for the prologue of functions that use %ebp as frame pointer
        self.uses_frame_pointer = True
        self.r_localvar = r_localvarfp
        return [InsnPrologue()]

    def _visit_epilogue(self):
        if not self.uses_frame_pointer:
            raise UnrecognizedOperation('epilogue without prologue')
        return [InsnEpilogue(4)]

    def visit_leave(self, line):
        return self._visit_epilogue() + self._visit_pop('%ebp')

    def visit_ret(self, line):
        return InsnRet()

    def visit_jmp(self, line):
        match = r_jmp_switch.match(line)
        if match:
            # this is a jmp *Label(%index), used for table-based switches.
            # Assume that the table is just a list of lines looking like
            # .long LABEL or .long 0, ending in a .text or .section .text.hot.
            tablelabel = match.group(1)
            tablelin = self.labels[tablelabel].lineno + 1
            while not r_jmptable_end.match(self.lines[tablelin]):
                match = r_jmptable_item.match(self.lines[tablelin])
                if not match:
                    raise NoPatternMatch(self.lines[tablelin])
                label = match.group(1)
                if label != '0':
                    self.register_jump_to(label)
                tablelin += 1
            return InsnStop()
        if r_unaryinsn_star.match(line):
            # that looks like an indirect tail-call.
            return InsnRet()    # tail-calls are equivalent to RET for us
        try:
            self.conditional_jump(line)
        except KeyError:
            # label not found: check if it's a tail-call turned into a jump
            match = r_unaryinsn.match(line)
            target = match.group(1)
            assert not target.startswith('.')
            return InsnRet()    # tail-calls are equivalent to RET for us
        return InsnStop()

    def register_jump_to(self, label):
        self.labels[label].previous_insns.append(self.insns[-1])

    def conditional_jump(self, line):
        match = r_jump.match(line)
        label = match.group(1)
        self.register_jump_to(label)
        return []

    visit_je = conditional_jump
    visit_jne = conditional_jump
    visit_jg = conditional_jump
    visit_jge = conditional_jump
    visit_jl = conditional_jump
    visit_jle = conditional_jump
    visit_ja = conditional_jump
    visit_jae = conditional_jump
    visit_jb = conditional_jump
    visit_jbe = conditional_jump
    visit_jp = conditional_jump
    visit_jnp = conditional_jump
    visit_js = conditional_jump
    visit_jns = conditional_jump
    visit_jo = conditional_jump
    visit_jno = conditional_jump

    def visit_call(self, line):
        match = r_unaryinsn.match(line)
        if match is None:
            assert r_unaryinsn_star.match(line)   # indirect call
        else:
            target = match.group(1)
            if target in FUNCTIONS_NOT_RETURNING:
                return InsnStop()
        return [InsnCall(self.currentlineno),
                InsnSetLocal('%eax')]      # the result is there


class UnrecognizedOperation(Exception):
    pass

class NoPatternMatch(Exception):
    pass

class SomeNewValue(object):
    pass
somenewvalue = SomeNewValue()


class Insn(object):
    _args_ = []
    _locals_ = []
    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__,
                           ', '.join([str(getattr(self, name))
                                      for name in self._args_]))
    def requestgcroots(self):
        return {}

    def source_of(self, localvar, tag):
        return localvar

class Label(Insn):
    _args_ = ['label', 'lineno']
    def __init__(self, label, lineno):
        self.label = label
        self.lineno = lineno
        self.previous_insns = []   # all insns that jump (or fallthrough) here

class InsnFunctionStart(Insn):
    framesize = 0
    previous_insns = ()
    def __init__(self):
        self.arguments = {}
        for reg in CALLEE_SAVE_REGISTERS:
            self.arguments[reg] = somenewvalue
    def source_of(self, localvar, tag):
        if localvar not in self.arguments:
            assert isinstance(localvar, int) and localvar > 0, (
                "must come from an argument to the function, got %r" %
                (localvar,))
            self.arguments[localvar] = somenewvalue
        return self.arguments[localvar]

class InsnSetLocal(Insn):
    _args_ = ['target']
    _locals_ = ['target']
    def __init__(self, target):
        self.target = target
    def source_of(self, localvar, tag):
        if localvar == self.target:
            return somenewvalue
        return localvar

class InsnCopyLocal(Insn):
    _args_ = ['source', 'target']
    _locals_ = ['source', 'target']
    def __init__(self, source, target):
        self.source = source
        self.target = target
    def source_of(self, localvar, tag):
        if localvar == self.target:
            return self.source
        return localvar

class InsnStackAdjust(Insn):
    _args_ = ['delta']
    def __init__(self, delta):
        assert delta % 4 == 0
        self.delta = delta

class InsnStop(Insn):
    pass

class InsnRet(InsnStop):
    framesize = 0
    def requestgcroots(self):
        return dict(zip(CALLEE_SAVE_REGISTERS, CALLEE_SAVE_REGISTERS))

class InsnCall(Insn):
    _args_ = ['lineno', 'gcroots']
    def __init__(self, lineno):
        # 'gcroots' is a dict built by side-effect during the call to
        # FunctionGcRootTracker.trackgcroots().  Its meaning is as follows:
        # the keys are the location that contain gc roots (either register
        # names like '%esi', or negative integer offsets relative to the end
        # of the function frame).  The value corresponding to a key is the
        # "tag", which is None for a normal gc root, or else the name of a
        # callee-saved register.  In the latter case it means that this is
        # only a gc root if the corresponding register in the caller was
        # really containing a gc pointer.  A typical example:
        #
        #     InsnCall({'%ebp': '%ebp', -8: '%ebx', '%esi': None})
        #
        # means that %esi is a gc root across this call; that %ebp is a
        # gc root if it was in the caller (typically because %ebp is not
        # modified at all in the current function); and that the word at 8
        # bytes before the end of the current stack frame is a gc root if
        # %ebx was a gc root in the caller (typically because the current
        # function saves and restores %ebx from there in the prologue and
        # epilogue).
        #
        self.gcroots = {}
        self.lineno = lineno

    def source_of(self, localvar, tag):
        self.gcroots[localvar] = tag
        return localvar

class InsnGCROOT(Insn):
    _args_ = ['loc']
    _locals_ = ['loc']
    def __init__(self, loc):
        self.loc = loc
    def requestgcroots(self):
        return {self.loc: None}

class InsnPrologue(Insn):
    def __setattr__(self, attr, value):
        if attr == 'framesize':
            assert value == 4, ("unrecognized function prologue - "
                                "only supports push %ebp; movl %esp, %ebp")
        Insn.__setattr__(self, attr, value)

class InsnEpilogue(Insn):
    def __init__(self, framesize=None):
        if framesize is not None:
            self.framesize = framesize


FUNCTIONS_NOT_RETURNING = {
    'abort': None,
    '_exit': None,
    '__assert_fail': None,
    }

CALLEE_SAVE_REGISTERS_NOEBP = ['%ebx', '%esi', '%edi']
CALLEE_SAVE_REGISTERS = CALLEE_SAVE_REGISTERS_NOEBP + ['%ebp']


if __name__ == '__main__':
    if sys.argv and sys.argv[1] == '-v':
        del sys.argv[1]
        verbose = sys.maxint
    else:
        verbose = 1
    tracker = GcRootTracker(verbose=verbose)
    for fn in sys.argv[1:]:
        tmpfn = fn + '.TMP'
        f = open(fn, 'r')
        g = open(tmpfn, 'w')
        tracker.process(f, g, filename=fn)
        f.close()
        g.close()
        os.unlink(fn)
        os.rename(tmpfn, fn)
    tracker.dump(sys.stdout)

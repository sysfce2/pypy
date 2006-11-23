from pypy.rpython.lltypesystem import lltype, llmemory

class Memo(object):
    _annspecialcase_ = 'specialize:ctr_location'

    def __init__(self):
        self.boxes = {}
        self.containers = {}

def enter_block_memo():
    return Memo()

def freeze_memo():
    return Memo()

def exactmatch_memo():
    memo = Memo()
    memo.partialdatamatch = {}
    return memo

def copy_memo():
    return Memo()

def unfreeze_memo():
    return Memo()


class RedBox(object):
    __slots__ = ['kind', 'genvar']

    def __init__(self, kind, genvar=None):
        self.kind = kind
        self.genvar = genvar    # None or a genvar

    def __repr__(self):
        if not self.genvar:
            return '<dummy>'
        else:
            return '<%r>' % (self.genvar,)

    def is_constant(self):
        return bool(self.genvar) and self.genvar.is_const

    def getgenvar(self, builder):
        return self.genvar

    def enter_block(self, incoming, memo):
        memo = memo.boxes
        if not self.is_constant() and self not in memo:
            incoming.append(self)
            memo[self] = None

    def forcevar(self, builder, memo):
        if self.is_constant():
            # cannot mutate constant boxes in-place
            box = self.copy(memo)
            box.genvar = builder.genop_same_as(self.kind, self.genvar)
            return box
        else:
            # force virtual containers
            self.getgenvar(builder)
            return self

    def replace(self, memo):
        memo = memo.boxes
        return memo.setdefault(self, self)


def ll_redboxcls(TYPE):
    if isinstance(TYPE, lltype.Ptr):
        return PtrRedBox
    elif TYPE is lltype.Float:
        return DoubleRedBox
    else:
        assert isinstance(TYPE, lltype.Primitive)
        assert TYPE is not lltype.Void, "cannot make red boxes of voids"
        # XXX what about long longs?
        return IntRedBox

def redboxbuilder_void(kind, gv_value):return None
def redboxbuilder_int(kind, gv_value): return IntRedBox(kind, gv_value)
def redboxbuilder_dbl(kind, gv_value): return DoubleRedBox(kind,gv_value)
def redboxbuilder_ptr(kind, gv_value): return PtrRedBox(kind, gv_value)

def ll_redboxbuilder(TYPE):
    if TYPE is lltype.Void:
        return redboxbuilder_void
    elif isinstance(TYPE, lltype.Ptr):
        return redboxbuilder_ptr
    elif TYPE is lltype.Float:
        return redboxbuilder_dbl
    else:
        assert isinstance(TYPE, lltype.Primitive)
        # XXX what about long longs?
        return redboxbuilder_int

def ll_fromvalue(jitstate, value):
    "Make a constant RedBox from a low-level value."
    gv = ll_gv_fromvalue(jitstate, value)
    T = lltype.typeOf(value)
    kind = jitstate.curbuilder.rgenop.kindToken(T)
    cls = ll_redboxcls(T)
    return cls(kind, gv)

def redbox_from_prebuilt_value(RGenOp, value):
    T = lltype.typeOf(value)
    kind = RGenOp.kindToken(T)
    gv = RGenOp.constPrebuiltGlobal(value)
    cls = ll_redboxcls(T)
    return cls(kind, gv)

def ll_gv_fromvalue(jitstate, value):
    rgenop = jitstate.curbuilder.rgenop
    gv = rgenop.genconst(value)
    return gv

def ll_getvalue(box, T):
    "Return the content of a known-to-be-constant RedBox."
    return box.genvar.revealconst(T)

def ll_is_constant(box):
    "Check if a red box is known to be constant."
    return box.is_constant()


class IntRedBox(RedBox):
    "A red box that contains a constant integer-like value."

    def copy(self, memo):
        memo = memo.boxes
        try:
            return memo[self]
        except KeyError:
            result = memo[self] = IntRedBox(self.kind, self.genvar)
            return result

    def freeze(self, memo):
        memo = memo.boxes
        try:
            return memo[self]
        except KeyError:
            if self.is_constant():
                result = FrozenIntConst(self.kind, self.genvar)
            else:
                result = FrozenIntVar(self.kind)
            memo[self] = result
            return result


class DoubleRedBox(RedBox):
    "A red box that contains a constant double-precision floating point value."

    def copy(self, memo):
        memo = memo.boxes
        try:
            return memo[self]
        except KeyError:
            result = memo[self] = DoubleRedBox(self.kind, self.genvar)
            return result

    def freeze(self, memo):
        memo = memo.boxes
        try:
            return memo[self]
        except KeyError:
            if self.is_constant():
                result = FrozenDoubleConst(self.kind, self.genvar)
            else:
                result = FrozenDoubleVar(self.kind)
            memo[self] = result
            return result


class PtrRedBox(RedBox):
    content = None   # or an AbstractContainer

    def __repr__(self):
        if not self.genvar and self.content is not None:
            return '<virtual %s>' % (self.content,)
        else:
            return RedBox.__repr__(self)

    def op_getfield(self, jitstate, fielddesc):
        if self.content is not None:
            box = self.content.op_getfield(jitstate, fielddesc)
            if box is not None:
                return box
        gv_ptr = self.getgenvar(jitstate.curbuilder)
        box = fielddesc.generate_get(jitstate.curbuilder, gv_ptr)
        if fielddesc.immutable:
            self.remember_field(fielddesc, box)
        return box

    def op_setfield(self, jitstate, fielddesc, valuebox):
        gv_ptr = self.genvar
        if gv_ptr:
            fielddesc.generate_set(jitstate.curbuilder, gv_ptr, valuebox)
        else:
            assert self.content is not None
            self.content.op_setfield(jitstate, fielddesc, valuebox)

    def op_getsubstruct(self, jitstate, fielddesc):
        gv_ptr = self.genvar
        if gv_ptr:
            return fielddesc.generate_getsubstruct(jitstate.curbuilder, gv_ptr)
        else:
            assert self.content is not None
            return self.content.op_getsubstruct(jitstate, fielddesc)

    def remember_field(self, fielddesc, box):
        if self.genvar.is_const:
            return      # no point in remembering field then
        if self.content is None:
            from pypy.jit.timeshifter import rcontainer
            self.content = rcontainer.PartialDataStruct()
        self.content.remember_field(fielddesc, box)

    def copy(self, memo):
        boxmemo = memo.boxes
        try:
            result = boxmemo[self]
        except KeyError:
            result = PtrRedBox(self.kind, self.genvar)
            boxmemo[self] = result
            if self.content:
                result.content = self.content.copy(memo)
        assert isinstance(result, PtrRedBox)
        return result

    def replace(self, memo):
        boxmemo = memo.boxes
        try:
            result = boxmemo[self]
        except KeyError:
            boxmemo[self] = self
            if self.content:
                self.content.replace(memo)
            result = self
        assert isinstance(result, PtrRedBox)
        return result

    def freeze(self, memo):
        boxmemo = memo.boxes
        try:
            return boxmemo[self]
        except KeyError:
            content = self.content
            if not self.genvar:
                from pypy.jit.timeshifter import rcontainer
                assert isinstance(content, rcontainer.VirtualContainer)
                result = FrozenPtrVirtual(self.kind)
                boxmemo[self] = result
                result.fz_content = content.freeze(memo)
                return result
            elif self.genvar.is_const:
                result = FrozenPtrConst(self.kind, self.genvar)
            elif content is None:
                result = FrozenPtrVar(self.kind)
            else:
                # if self.content is not None, it's a PartialDataStruct
                from pypy.jit.timeshifter import rcontainer
                assert isinstance(content, rcontainer.PartialDataStruct)
                result = FrozenPtrVarWithPartialData(self.kind)
                boxmemo[self] = result
                result.fz_partialcontent = content.partialfreeze(memo)
                return result
            boxmemo[self] = result
            return result

    def getgenvar(self, builder):
        if not self.genvar:
            content = self.content
            from pypy.jit.timeshifter import rcontainer
            assert isinstance(content, rcontainer.VirtualContainer)
            content.force_runtime_container(builder)
            assert self.genvar
        return self.genvar

##    def forcevar(self, builder, memo):
##        RedBox.forcevar(self, builder, memo)
##        # if self.content is still there, it's a PartialDataStruct
##        # - for now, we always remove it in this situation
##        self.content = None

    def enter_block(self, incoming, memo):
        if self.genvar:
            RedBox.enter_block(self, incoming, memo)
        if self.content:
            self.content.enter_block(incoming, memo)

# ____________________________________________________________

class FrozenValue(object):
    """An abstract value frozen in a saved state.
    """
    def __init__(self, kind):
        self.kind = kind

    def is_constant_equal(self, box):
        return False


class FrozenConst(FrozenValue):

    def exactmatch(self, box, outgoingvarboxes, memo):
        if self.is_constant_equal(box):
            return True
        else:
            outgoingvarboxes.append(box)
            return False


class FrozenVar(FrozenValue):

    def exactmatch(self, box, outgoingvarboxes, memo):
        memo = memo.boxes
        if self not in memo:
            memo[self] = box
            outgoingvarboxes.append(box)
            return True
        elif memo[self] is box:
            return True
        else:
            outgoingvarboxes.append(box)
            return False


class FrozenIntConst(FrozenConst):

    def __init__(self, kind, gv_const):
        self.kind = kind
        self.gv_const = gv_const

    def is_constant_equal(self, box):
        return (box.is_constant() and
                self.gv_const.revealconst(lltype.Signed) ==
                box.genvar.revealconst(lltype.Signed))

    def unfreeze(self, incomingvarboxes, memo):
        # XXX could return directly the original IntRedBox
        return IntRedBox(self.kind, self.gv_const)


class FrozenIntVar(FrozenVar):

    def unfreeze(self, incomingvarboxes, memo):
        memo = memo.boxes
        if self not in memo:
            newbox = IntRedBox(self.kind, None)
            incomingvarboxes.append(newbox)
            memo[self] = newbox
            return newbox
        else:
            return memo[self]


class FrozenDoubleConst(FrozenConst):

    def __init__(self, kind, gv_const):
        self.kind = kind
        self.gv_const = gv_const

    def is_constant_equal(self, box):
        return (box.is_constant() and
                self.gv_const.revealconst(lltype.Float) ==
                box.genvar.revealconst(lltype.Float))

    def unfreeze(self, incomingvarboxes, memo):
        return DoubleRedBox(self.kind, self.gv_const)


class FrozenDoubleVar(FrozenVar):

    def unfreeze(self, incomingvarboxes, memo):
        memo = memo.boxes
        if self not in memo:
            newbox = DoubleRedBox(self.kind, None)
            incomingvarboxes.append(newbox)
            memo[self] = newbox
            return newbox
        else:
            return memo[self]


class FrozenPtrConst(FrozenConst):

    def __init__(self, kind, gv_const):
        self.kind = kind
        self.gv_const = gv_const

    def is_constant_equal(self, box):
        return (box.is_constant() and
                self.gv_const.revealconst(llmemory.Address) ==
                box.genvar.revealconst(llmemory.Address))

    def exactmatch(self, box, outgoingvarboxes, memo):
        assert isinstance(box, PtrRedBox)
        memo.partialdatamatch[box] = None     # could do better
        return FrozenConst.exactmatch(self, box, outgoingvarboxes, memo)

    def unfreeze(self, incomingvarboxes, memo):
        return PtrRedBox(self.kind, self.gv_const)


class FrozenPtrVar(FrozenVar):

    def exactmatch(self, box, outgoingvarboxes, memo):
        assert isinstance(box, PtrRedBox)
        memo.partialdatamatch[box] = None
        return FrozenVar.exactmatch(self, box, outgoingvarboxes, memo)

    def unfreeze(self, incomingvarboxes, memo):
        memo = memo.boxes
        if self not in memo:
            newbox = PtrRedBox(self.kind, None)
            incomingvarboxes.append(newbox)
            memo[self] = newbox
            return newbox
        else:
            return memo[self]


class FrozenPtrVarWithPartialData(FrozenPtrVar):

    def exactmatch(self, box, outgoingvarboxes, memo):
        if self.fz_partialcontent is None:
            return FrozenPtrVar.exactmatch(self, box, outgoingvarboxes, memo)
        assert isinstance(box, PtrRedBox)
        partialdatamatch = self.fz_partialcontent.match(box,
                                                        memo.partialdatamatch)
        # skip the parent's exactmatch()!
        exact = FrozenVar.exactmatch(self, box, outgoingvarboxes, memo)
        return exact and partialdatamatch


class FrozenPtrVirtual(FrozenValue):

    def exactmatch(self, box, outgoingvarboxes, memo):
        assert isinstance(box, PtrRedBox)
        if box.genvar:
            outgoingvarboxes.append(box)
            return False
        else:
            assert box.content is not None
            return self.fz_content.exactmatch(box.content, outgoingvarboxes,
                                              memo)

    def unfreeze(self, incomingvarboxes, memo):
        return self.fz_content.unfreeze(incomingvarboxes, memo)


##class FrozenPtrVarWithData(FrozenValue):

##    def exactmatch(self, box, outgoingvarboxes, memo):
##        memo = memo.boxes
##        if self not in memo:
##            memo[self] = box
##            outgoingvarboxes.append(box)
##            return True
##        elif memo[self] is box:
##            return True
##        else:
##            outgoingvarboxes.append(box)
##            return False

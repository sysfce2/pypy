""" Code to feed information from the optimizer via the resume code into the
optimizer of the bridge attached to a guard. """

from rpython.jit.metainterp import resumecode

from rpython.rlib.debug import (have_debug_prints, debug_start, debug_stop,
    debug_print)

# adds the following sections at the end of the resume code:
#
# ---- known classes
# <bitfield> size is the number of reference boxes in the liveboxes
#            1 klass known
#            0 klass unknown
#            (the class is found by actually looking at the runtime value)
#            the bits are bunched in bunches of 7
#
# ---- heap knowledge
# <length>
# (<box1> <descr> <box2>) length times, if getfield(box1, descr) == box2
#                         both boxes should be in the liveboxes
#
# <length>
# (<box1> <index> <descr> <box2>) length times, if getarrayitem_gc(box1, index, descr) == box2
#                                 both boxes should be in the liveboxes
#
# ----


# maybe should be delegated to the optimization classes?

def tag_box(box, liveboxes_from_env, memo):
    from rpython.jit.metainterp.history import Const
    if isinstance(box, Const):
        return memo.getconst(box)
    else:
        return liveboxes_from_env[box] # has to exist

def decode_box(resumestorage, tagged, liveboxes, cpu):
    from rpython.jit.metainterp.resume import untag, TAGCONST, TAGINT, TAGBOX
    from rpython.jit.metainterp.resume import NULLREF, TAG_CONST_OFFSET, tagged_eq
    from rpython.jit.metainterp.history import ConstInt
    num, tag = untag(tagged)
    # NB: the TAGVIRTUAL case can't happen here, because this code runs after
    # virtuals are already forced again
    if tag == TAGCONST:
        if tagged_eq(tagged, NULLREF):
            box = cpu.ts.CONST_NULL
        else:
            box = resumestorage.rd_consts[num - TAG_CONST_OFFSET]
    elif tag == TAGINT:
        box = ConstInt(num)
    elif tag == TAGBOX:
        box = liveboxes[num]
    else:
        raise AssertionError("unreachable")
    return box

def serialize_optimizer_knowledge(optimizer, numb_state, liveboxes, liveboxes_from_env, memo):
    available_boxes = {}
    for box in liveboxes:
        if box is not None and box in liveboxes_from_env:
            available_boxes[box] = None

    # class knowledge is stored as bits, true meaning the class is known, false
    # means unknown. on deserializing we look at the bits, and read the runtime
    # class for the known classes (which has to be the same in the bridge) and
    # mark that as known. this works for guard_class too: the class is only
    # known *after* the guard
    bitfield = 0
    shifts = 0
    for box in liveboxes:
        if box is None or box.type != "r":
            continue
        info = optimizer.getptrinfo(box)
        known_class = info is not None and info.get_known_class(optimizer.cpu) is not None
        bitfield <<= 1
        bitfield |= known_class
        shifts += 1
        if shifts == 6:
            numb_state.append_int(bitfield)
            bitfield = shifts = 0
    if shifts:
        numb_state.append_int(bitfield << (6 - shifts))

    # heap knowledge: we store triples of known heap fields in non-virtual
    # structs
    if optimizer.optheap:
        triples_struct, triples_array = optimizer.optheap.serialize_optheap(available_boxes)
        # can only encode descrs that have a known index into
        # metainterp_sd.all_descrs
        triples_struct = [triple for triple in triples_struct if triple[1].descr_index != -1]
        numb_state.append_int(len(triples_struct))
        for box1, descr, box2 in triples_struct:
            descr_index = descr.descr_index
            numb_state.append_short(tag_box(box1, liveboxes_from_env, memo))
            numb_state.append_int(descr_index)
            numb_state.append_short(tag_box(box2, liveboxes_from_env, memo))
        numb_state.append_int(len(triples_array))
        for box1, index, descr, box2 in triples_array:
            descr_index = descr.descr_index
            numb_state.append_short(tag_box(box1, liveboxes_from_env, memo))
            numb_state.append_int(index)
            numb_state.append_int(descr_index)
            numb_state.append_short(tag_box(box2, liveboxes_from_env, memo))
    else:
        numb_state.append_int(0)
        numb_state.append_int(0)

def deserialize_optimizer_knowledge(optimizer, resumestorage, frontend_boxes, liveboxes):
    debug_start("jit-bridge-deserialize")

    reader = resumecode.Reader(resumestorage.rd_numb)
    assert len(frontend_boxes) == len(liveboxes)
    metainterp_sd = optimizer.metainterp_sd

    # skip resume section
    startcount = reader.next_item()
    reader.jump(startcount - 1)

    # class knowledge
    debug_print("# class knowledge")
    bitfield = 0
    mask = 0
    for i, box in enumerate(liveboxes):
        if box.type != "r":
            continue
        if not mask:
            bitfield = reader.next_item()
            mask = 0b100000
        class_known = bitfield & mask
        mask >>= 1
        if class_known:
            cls = optimizer.cpu.ts.cls_of_box(frontend_boxes[i])
            optimizer.make_constant_class(box, cls)
            debug_print("class known", i)
        else:
            debug_print("class NOT known", i)

    # heap knowledge
    debug_print("# heap knowledge")
    if not optimizer.optheap:
        debug_print("# no optheap!")
        return
    length = reader.next_item()
    result_struct = []
    for i in range(length):
        tagged = reader.next_item()
        box1 = decode_box(resumestorage, tagged, liveboxes, metainterp_sd.cpu)
        descr_index = reader.next_item()
        descr = metainterp_sd.all_descrs[descr_index]
        tagged = reader.next_item()
        box2 = decode_box(resumestorage, tagged, liveboxes, metainterp_sd.cpu)
        result_struct.append((box1, descr, box2))

        attrname = descr.repr_of_descr()
        try:
            i1 = liveboxes.index(box1)
            i2 = liveboxes.index(box2)
        except ValueError:
            debug_print("getfield: some unknown box with field", attrname)
        else:
            debug_print("getfield:", i1, i2, attrname)
    length = reader.next_item()
    result_array = []
    for i in range(length):
        tagged = reader.next_item()
        box1 = decode_box(resumestorage, tagged, liveboxes, metainterp_sd.cpu)
        index = reader.next_item()
        descr_index = reader.next_item()
        descr = metainterp_sd.all_descrs[descr_index]
        tagged = reader.next_item()
        box2 = decode_box(resumestorage, tagged, liveboxes, metainterp_sd.cpu)
        result_array.append((box1, index, descr, box2))
    optimizer.optheap.deserialize_optheap(result_struct, result_array)

    debug_stop("jit-bridge-deserialize")

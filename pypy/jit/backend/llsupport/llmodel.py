import sys
from pypy.rpython.lltypesystem import lltype, llmemory, rffi, rclass, rstr
from pypy.rlib.objectmodel import we_are_translated, specialize
from pypy.jit.metainterp.history import BoxInt, BoxPtr, set_future_values
from pypy.jit.backend.model import AbstractCPU
from pypy.jit.backend.logger import LLLogger
from pypy.jit.backend.llsupport import symbolic
from pypy.jit.backend.llsupport.symbolic import WORD, unroll_basic_sizes
from pypy.jit.backend.llsupport.descr import get_size_descr,  BaseSizeDescr
from pypy.jit.backend.llsupport.descr import get_field_descr, BaseFieldDescr
from pypy.jit.backend.llsupport.descr import get_array_descr, BaseArrayDescr
from pypy.jit.backend.llsupport.descr import get_call_descr,  BaseCallDescr

def _check_addr_range(x):
    if sys.platform == 'linux2':
        # this makes assumption about address ranges that are valid
        # only on linux (?)
        assert x == 0 or x > (1<<20) or x < (-1<<20)        


class AbstractLLCPU(AbstractCPU):
    is_oo = False
    logger_cls = LLLogger

    def __init__(self, rtyper, stats, translate_support_code=False,
                 gcdescr=None):
        from pypy.jit.backend.llsupport.gc import get_ll_description
        self.rtyper = rtyper
        self.stats = stats
        self.translate_support_code = translate_support_code
        self._call_cache = {}
        self.gc_ll_descr = get_ll_description(gcdescr, self)
        self.vtable_offset, _ = symbolic.get_field_token(rclass.OBJECT,
                                                         'typeptr',
                                                        translate_support_code)

    def set_class_sizes(self, class_sizes):
        self.class_sizes = class_sizes

    # ------------------- helpers and descriptions --------------------

    @staticmethod
    def cast_adr_to_int(x):
        res = rffi.cast(lltype.Signed, x)
        return res

    @staticmethod
    def cast_int_to_gcref(x):
        if not we_are_translated():
            _check_addr_range(x)
        return rffi.cast(llmemory.GCREF, x)

    @staticmethod
    def cast_gcref_to_int(x):
        return rffi.cast(lltype.Signed, x)

    @staticmethod
    def cast_int_to_adr(x):
        if not we_are_translated():
            _check_addr_range(x)
        return rffi.cast(llmemory.Address, x)

    def sizeof(self, S):
        return get_size_descr(S, self.translate_support_code)

    def fielddescrof(self, STRUCT, fieldname):
        return get_field_descr(STRUCT, fieldname, self.translate_support_code)

    def unpack_fielddescr(self, fielddescr):
        assert isinstance(fielddescr, BaseFieldDescr)
        ofs = fielddescr.offset
        size = fielddescr.get_field_size(self.translate_support_code)
        ptr = fielddescr.is_pointer_field()
        return ofs, size, ptr
    unpack_fielddescr._always_inline_ = True

    def arraydescrof(self, A):
        return get_array_descr(A)

    def unpack_arraydescr(self, arraydescr):
        assert isinstance(arraydescr, BaseArrayDescr)
        ofs = arraydescr.get_base_size(self.translate_support_code)
        size = arraydescr.get_item_size(self.translate_support_code)
        ptr = arraydescr.is_array_of_pointers()
        return ofs, size, ptr
    unpack_arraydescr._always_inline_ = True

    def calldescrof(self, FUNC, ARGS, RESULT):
        return get_call_descr(ARGS, RESULT, self.translate_support_code,
                              self._call_cache)

    # ____________________________________________________________

    def do_arraylen_gc(self, args, arraydescr):
        assert isinstance(arraydescr, BaseArrayDescr)
        ofs = arraydescr.get_ofs_length(self.translate_support_code)
        gcref = args[0].getptr_base()
        length = rffi.cast(rffi.CArrayPtr(lltype.Signed), gcref)[ofs/WORD]
        return BoxInt(length)

    def do_getarrayitem_gc(self, args, arraydescr):
        itemindex = args[1].getint()
        gcref = args[0].getptr_base()
        ofs, size, ptr = self.unpack_arraydescr(arraydescr)
        #
        for TYPE, itemsize in unroll_basic_sizes:
            if size == itemsize:
                val = (rffi.cast(rffi.CArrayPtr(TYPE), gcref)
                       [ofs/itemsize + itemindex])
                val = rffi.cast(lltype.Signed, val)
                break
        else:
            raise NotImplementedError("size = %d" % size)
        if ptr:
            return BoxPtr(self.cast_int_to_gcref(val))
        else:
            return BoxInt(val)

    def do_setarrayitem_gc(self, args, arraydescr):
        itemindex = args[1].getint()
        gcref = args[0].getptr_base()
        ofs, size, ptr = self.unpack_arraydescr(arraydescr)
        vbox = args[2]
        #
        if ptr:
            vboxptr = vbox.getptr_base()
            self.gc_ll_descr.do_write_barrier(gcref, vboxptr)
            a = rffi.cast(rffi.CArrayPtr(lltype.Signed), gcref)
            a[ofs/WORD + itemindex] = self.cast_gcref_to_int(vboxptr)
        else:
            v = vbox.getint()
            for TYPE, itemsize in unroll_basic_sizes:
                if size == itemsize:
                    a = rffi.cast(rffi.CArrayPtr(TYPE), gcref)
                    a[ofs/itemsize + itemindex] = rffi.cast(TYPE, v)
                    break
            else:
                raise NotImplementedError("size = %d" % size)

    def _new_do_len(TP):
        def do_strlen(self, args, descr=None):
            basesize, itemsize, ofs_length = symbolic.get_array_token(TP,
                                                self.translate_support_code)
            gcref = args[0].getptr_base()
            v = rffi.cast(rffi.CArrayPtr(lltype.Signed), gcref)[ofs_length/WORD]
            return BoxInt(v)
        return do_strlen

    do_strlen = _new_do_len(rstr.STR)
    do_unicodelen = _new_do_len(rstr.UNICODE)

    def do_strgetitem(self, args, descr=None):
        basesize, itemsize, ofs_length = symbolic.get_array_token(rstr.STR,
                                                    self.translate_support_code)
        gcref = args[0].getptr_base()
        i = args[1].getint()
        v = rffi.cast(rffi.CArrayPtr(lltype.Char), gcref)[basesize + i]
        return BoxInt(ord(v))

    def do_unicodegetitem(self, args, descr=None):
        basesize, itemsize, ofs_length = symbolic.get_array_token(rstr.UNICODE,
                                                    self.translate_support_code)
        gcref = args[0].getptr_base()
        i = args[1].getint()
        basesize = basesize // itemsize
        v = rffi.cast(rffi.CArrayPtr(lltype.UniChar), gcref)[basesize + i]
        return BoxInt(ord(v))

    @specialize.argtype(1)
    def _base_do_getfield(self, gcref, fielddescr):
        ofs, size, ptr = self.unpack_fielddescr(fielddescr)
        for TYPE, itemsize in unroll_basic_sizes:
            if size == itemsize:
                val = rffi.cast(rffi.CArrayPtr(TYPE), gcref)[ofs/itemsize]
                val = rffi.cast(lltype.Signed, val)
                break
        else:
            raise NotImplementedError("size = %d" % size)
        if ptr:
            return BoxPtr(self.cast_int_to_gcref(val))
        else:
            return BoxInt(val)

    def do_getfield_gc(self, args, fielddescr):
        gcref = args[0].getptr_base()
        return self._base_do_getfield(gcref, fielddescr)

    def do_getfield_raw(self, args, fielddescr):
        return self._base_do_getfield(args[0].getint(), fielddescr)

    @specialize.argtype(1)
    def _base_do_setfield(self, gcref, vbox, fielddescr):
        ofs, size, ptr = self.unpack_fielddescr(fielddescr)
        if ptr:
            assert lltype.typeOf(gcref) is not lltype.Signed, (
                "can't handle write barriers for setfield_raw")
            ptr = vbox.getptr_base()
            self.gc_ll_descr.do_write_barrier(gcref, ptr)
            a = rffi.cast(rffi.CArrayPtr(lltype.Signed), gcref)
            a[ofs/WORD] = self.cast_gcref_to_int(ptr)
        else:
            v = vbox.getint()
            for TYPE, itemsize in unroll_basic_sizes:
                if size == itemsize:
                    v = rffi.cast(TYPE, v)
                    rffi.cast(rffi.CArrayPtr(TYPE), gcref)[ofs/itemsize] = v
                    break
            else:
                raise NotImplementedError("size = %d" % size)

    def do_setfield_gc(self, args, fielddescr):
        gcref = args[0].getptr_base()
        self._base_do_setfield(gcref, args[1], fielddescr)

    def do_setfield_raw(self, args, fielddescr):
        self._base_do_setfield(args[0].getint(), args[1], fielddescr)

    def do_new(self, args, sizedescr):
        res = self.gc_ll_descr.gc_malloc(sizedescr)
        return BoxPtr(res)

    def do_new_with_vtable(self, args, descr=None):
        assert descr is None
        classint = args[0].getint()
        descrsize = self.class_sizes[classint]
        res = self.gc_ll_descr.gc_malloc(descrsize)
        as_array = rffi.cast(rffi.CArrayPtr(lltype.Signed), res)
        as_array[self.vtable_offset/WORD] = classint
        return BoxPtr(res)

    def do_new_array(self, args, arraydescr):
        num_elem = args[0].getint()
        res = self.gc_ll_descr.gc_malloc_array(arraydescr, num_elem)
        return BoxPtr(res)

    def do_newstr(self, args, descr=None):
        num_elem = args[0].getint()
        res = self.gc_ll_descr.gc_malloc_str(num_elem)
        return BoxPtr(res)

    def do_newunicode(self, args, descr=None):
        num_elem = args[0].getint()
        res = self.gc_ll_descr.gc_malloc_unicode(num_elem)
        return BoxPtr(res)

    def do_strsetitem(self, args, descr=None):
        basesize, itemsize, ofs_length = symbolic.get_array_token(rstr.STR,
                                                self.translate_support_code)
        index = args[1].getint()
        v = args[2].getint()
        a = args[0].getptr_base()
        rffi.cast(rffi.CArrayPtr(lltype.Char), a)[index + basesize] = chr(v)

    def do_unicodesetitem(self, args, descr=None):
        basesize, itemsize, ofs_length = symbolic.get_array_token(rstr.UNICODE,
                                                self.translate_support_code)
        index = args[1].getint()
        v = args[2].getint()
        a = args[0].getptr_base()
        basesize = basesize // itemsize
        rffi.cast(rffi.CArrayPtr(lltype.UniChar), a)[index + basesize] = unichr(v)

    def do_call(self, args, calldescr):
        assert isinstance(calldescr, BaseCallDescr)
        assert len(args) == 1 + len(calldescr.arg_classes)
        if not we_are_translated():
            assert ([cls.type for cls in calldescr.arg_classes] ==
                    [arg.type for arg in args[1:]])
        loop = calldescr.get_loop_for_call(self)
        set_future_values(self, args)
        self.execute_operations(loop)
        # Note: if an exception is set, the rest of the code does a bit of
        # nonsense but nothing wrong (the return value should be ignored)
        if calldescr.returns_a_pointer():
            return BoxPtr(self.get_latest_value_ptr(0))
        elif calldescr.get_result_size(self.translate_support_code) != 0:
            return BoxInt(self.get_latest_value_int(0))
        else:
            return None

    def do_cast_ptr_to_int(self, args, descr=None):
        return BoxInt(self.cast_gcref_to_int(args[0].getptr_base()))

    def do_cast_int_to_ptr(self, args, descr=None):
        return BoxPtr(self.cast_int_to_gcref(args[0].getint()))


import pypy.jit.metainterp.executor
pypy.jit.metainterp.executor.make_execute_list(AbstractLLCPU)

from pypy.jit.metainterp.history import ResOperation, BoxInt, ConstInt,\
     BoxPtr, ConstPtr, TreeLoop
from pypy.jit.metainterp.resoperation import rop
from pypy.jit.backend.x86.runner import CPU

def test_bug_rshift():
    v1 = BoxInt()
    v2 = BoxInt()
    v3 = BoxInt()
    v4 = BoxInt()
    loop = TreeLoop('test')
    loop.inputargs = [v1]
    loop.operations = [
        ResOperation(rop.INT_ADD, [v1, v1], v2),
        ResOperation(rop.INT_INVERT, [v2], v3),
        ResOperation(rop.UINT_RSHIFT, [v1, ConstInt(3)], v4),
        ResOperation(rop.FAIL, [v4, v3], None),
        ]
    cpu = CPU(None, None)
    cpu.compile_operations(loop)
    cpu.execute_operations(loop, [BoxInt(9)])
    assert v4.value == (9 >> 3)
    assert v3.value == (~18)

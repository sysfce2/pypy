import pytest
from rpython.translator.translator import TranslationContext, graphof
from rpython.translator.backendopt.cse import CSE, Cache, loop_blocks
from rpython.flowspace.model import Variable, Constant
from rpython.translator.backendopt import removenoops
from rpython.flowspace.model import checkgraph, summary
from rpython.conftest import option
from rpython.rlib import jit

class TestStoreSink(object):
    def translate(self, func, argtypes):
        t = TranslationContext()
        t.buildannotator().build_types(func, argtypes)
        t.buildrtyper().specialize()
        return t

    def check(self, f, argtypes, fullopts=False, **expected):
        from rpython.translator.backendopt import inline, all, constfold
        t = self.translate(f, argtypes)
        getfields = 0
        graph = graphof(t, f)
        if option.view:
            t.view()
        if fullopts:
            all.backend_optimizations(t)
        removenoops.remove_same_as(graph)
        checkgraph(graph)
        cse = CSE(t)
        cse.transform(graph)
        if option.view:
            t.view()
        checkgraph(graph)
        s = summary(graph)
        for key, val in expected.items():
            assert s.get(key, 0) == val
        assert "same_as" not in s

    def test_infrastructure(self):
        def f(i):
            x = (i + 1) * (i + 1)
            y = (i + 1) * (i + 1)
            return x - y

        self.check(f, [int], int_add=1, int_mul=1)

    def test_split(self):
        def f(i, j):
            k = i + 1
            if j:
                return i + 1
            return k * (i + 1)

        self.check(f, [int, int], int_add=1)

    def test_merge(self):
        def f(i, j):
            if j:
                k = i + 1
                j = 1
            else:
                j = i + 1
                k = 5
            return k * j * (i + 1)

        # an add in each branch, but not the final block
        self.check(f, [int, int], int_add=2)

    def test_merge2(self):
        # in this test we add two different values, but the final add is on the
        # same different value, so it can be shared
        def f(i, j):
            if j:
                x = i
                y = x + 1
            else:
                x = ~i
                y = x + 1
            return (x + 1) * y

        # an add in each branch, but not the final block
        self.check(f, [int, int], int_add=2)

    def test_optimize_across_merge(self):
        def f(i, j):
            k = i + 1
            if j:
                j = 1
            else:
                j = i + 1
            return k * j * (i + 1)
        self.check(f, [int, int], int_add=1)


    def test_getfield(self):
        class A(object):
            pass

        def f(i):
            a = A()
            a.x = i
            return a.x + a.x

        self.check(f, [int], getfield=0)

    def test_irrelevant_setfield(self):
        class A(object):
            pass

        def f(i):
            a = A()
            a.x = i
            one = a.x
            a.y = 3
            two = a.x
            return one + two

        self.check(f, [int], getfield=0)

    def test_relevant_setfield(self):
        class A(object):
            pass

        def f(i):
            a = A()
            b = A()
            a.x = i
            b.x = i + 1
            one = a.x
            b.x = i
            two = a.x
            return one + two

        self.check(f, [int], getfield=2)

    def test_different_concretetype(self):
        class A(object):
            pass

        class B(object):
            pass

        def f(i):
            a = A()
            b = B()
            a.x = i
            one = a.x
            b.x = i + 1
            two = a.x
            return one + two

        self.check(f, [int], getfield=0)

    def test_subclass(self):
        class A(object):
            pass

        class B(A):
            pass

        def f(i):
            a = A()
            b = B()
            a.x = i
            one = a.x
            b.x = i + 1
            two = a.x
            return one + two

        self.check(f, [int], getfield=1)

    def test_two_getfields(self):
        class A(object):
            pass
        class B(object):
            pass
        a1 = A()
        a1.next = B()
        a1.next.x = 1
        a2 = A()
        a2.next = B()
        a2.next.x = 5


        def f(i):
            if i:
                a = a1
            else:
                a = a2
            return a.next.x + a.next.x + i

        self.check(f, [int], getfield=2)


    def test_bug_1(self):
        class A(object):
            pass

        def f(i):
            a = A()
            a.cond = i > 0
            n = a.cond
            if a.cond:
                return True
            return n

        self.check(f, [int], getfield=0)


    def test_cfg_splits_getfield(self):
        class A(object):
            pass

        def f(i):
            a = A()
            j = i
            for i in range(i):
                a.x = i
                if i:
                    j = a.x + a.x
                else:
                    j = a.x * 5
            return j

        self.check(f, [int], getfield=0)

    def test_malloc_does_not_invalidate(self):
        class A(object):
            pass
        class B(object):
            pass

        def f(i):
            a = A()
            a.x = i
            b = B()
            return a.x

        self.check(f, [int], getfield=0)

    def test_merge_heapcache(self):
        class A(object):
            pass

        def f(i):
            a = A()
            j = i
            for i in range(i):
                a.x = i
                if i:
                    j = a.x + a.x
                else:
                    j = a.x * 5
                j += a.x
            return j

        self.check(f, [int], getfield=0)

    def test_merge2_heapcache(self):
        class A(object):
            pass

        def f(i):
            a1 = A()
            a1.x = i
            a2 = A()
            a2.x = i + 1
            a3 = A()
            a3.x = 1 # clear other caches
            if i:
                a = a1
                j = a.x
            else:
                a = a2
                j = a.x
            j += a.x
            return j

        self.check(f, [int], getfield=2)

    def test_dont_invalidate_on_call(self):
        class A(object):
            pass
        class B(object):
            pass
        def g(b, a):
            b.x = 1
            a.y = 2

        def f(i):
            a = A()
            a.x = i
            a.y = i + 1
            b = B()
            g(b, a)
            return a.x + a.y

        self.check(f, [int], getfield=1)

    def test_do_invalidate_on_call_with_exception(self):
        class A(object):
            pass
        class B(object):
            pass
        def g(b, a):
            if a.x == 1000:
                raise ValueError
            b.x = 1
            a.x = 10
            a.y = 2

        def f(i):
            a = A()
            a.x = i
            a.y = i + 1
            b = B()
            if i:
                try:
                    g(b, a)
                except Exception:
                    pass
            return a.x + a.y

        self.check(f, [int], getfield=2)

    def test_loopinvariant(self):
        def f(i):
            x = i + 1
            res = 0
            while x:
                x -= 1
                res += i + 1
            return res
        self.check(f, [int], int_add=2)


    def test_loopinvariant_heap(self):
        class A(object):
            pass
        def f(i):
            a = A()
            a.x = i
            res = 0
            x = i
            while x:
                x -= 1
                res += a.x
            return res
        self.check(f, [int], getfield=0)

    def test_loopinvariant_heap_merge(self):
        class A(object):
            pass
        def f(i):
            res = 0
            x = i
            a = A()
            if i == 0:
                a.x = 1
            else:
                a.x = i
            while x:
                x -= 1
                res += a.x
            return res
        self.check(f, [int], getfield=0)

    def test_loopinvariant_heap_merge_not_possible(self):
        class A(object):
            pass
        def f(i):
            res = 0
            x = i
            a = A()
            if i == 0:
                a.x = 1
            else:
                a.x = i
            while x:
                x -= 1
                res += a.x
                if x % 1000 == 1:
                    a.x = 5
            return res
        self.check(f, [int], getfield=1)

    def test_loopinvariant_heap_merge_nested(self):
        class A(object):
            pass
        def f(i):
            res = 0
            y = 0
            while y < i:
                y += 1
                x = i
                a = A()
                if i == 0:
                    a.x = 1
                else:
                    a.x = i
                while x:
                    x -= 1
                    res += a.x
                    if x % 1000 == 1:
                        a.x = 5
            return res
        self.check(f, [int], getfield=1)

    def test_direct_merge(self):
        def f(i):
            a = i + 1
            if i:
                x = a
            else:
                x = a
            res = 0
            while a:
                res += i + 1
            return a + (i + 1)
        self.check(f, [int], add=0)

    def test_bug_2(self):
        class A(object):
            def getslice(self, a, b):
                return "a" * a * b

        def make(i):
            a = A()
            a.size = i * 12
            a.pos = i * 54
            return a

        def read(i, num):
            self = make(i)
            if num < 0:
                # read all
                eol = self.size
            else:
                eol = self.pos + num
                if eol > self.size:
                    eol = self.size

            res = self.getslice(self.pos, eol - self.pos)
            self.pos += len(res)
            return res
        self.check(read, [int, int])

    def test_immutable_getfield(self):
        class A(object):
            _immutable_fields_ = ['a']
            def __init__(self, a):
                self.a = a
        class B(object):
            pass
        a1 = A(5)
        a2 = A(8)

        def read(i):
            b = B()
            if i:
                b.a = a1
                return b.a.a
            b.a = a2
            return b.a.a
        self.check(read, [int], getfield=0)

        # not immutable
        class A(object):
            def __init__(self, a):
                self.a = a
        a1 = A(5)
        a2 = A(8)

        def read(i):
            if i:
                return a1.a
            return a2.a
        self.check(read, [int], getfield=2)

    def test_cast_pointer_introduce_aliases(self):
        class A(object):
            pass
        class B(A):
            pass
        class C(B):
            pass
        def f(i):
            res = 0
            if i > 10:
                if i > 20:
                    a = C()
                    a.x = 1
                    a.__class__
                else:
                    a = B()
                    a.x = 2
                    a.__class__
                # here a is a subclass of B
                res += a.x
            else:
                a = A()
                a.__class__
            res += a.__class__ is A
            return res
        self.check(f, [int], getfield=0)

    def test_cast_pointer_leading_to_constant(self):
        class Cls(object):
            pass
        class Sub(Cls):
            _immutable_fields_ = ['user_overridden_class']
        cls1 = Cls()
        cls2 = Sub()
        cls2.user_overridden_class = True
        cls3 = Sub()
        cls3.user_overridden_class = False
        class A(object):
            pass
        def f(i):
            res = 0
            if i > 20:
                a = A()
                a.cls = cls1
                return 1
            elif i > 30:
                a = A()
                a.cls = cls2
                cls = a.cls
                assert type(cls) is Sub
                return cls.user_overridden_class
            else:
                a = A()
                a.cls = cls3
                cls = a.cls
                assert type(cls) is Sub
                return cls.user_overridden_class
        self.check(f, [int], getfield=0)

    def test_dont_fold_virtualizable(self):
        class A(object):
            _virtualizable_ = ["x[*]", "y"]

        a1 = A()
        a1.x = [1, 2, 3]
        a1.y = 2
        a2 = A()
        a2.x = [65, 4, 3]
        a2.y = 8
        def f(i):
            if i:
                a = a1
            else:
                a = a2
            res = a.x[0]
            res += a.y
            if i == 10:
                res += a.x[1]
                res += a.y
            return res
        self.check(f, [int], getfield=3)

    def test_remove_unnecessary_setfield(self):
        class A(object):
            pass
        def f(i):
            res = 0
            x = i
            a = A()
            if i == 0:
                a.x = 1
                a.x = 1
            else:
                a.x = i
                a.x = a.x
                a.x = i
        self.check(f, [int], setfield=3)

    def test_malloc_varsize_getarraysize(self):
        def f(i):
            if i == 1:
                l = [1]
            else:
                l = [2, 3]
            return len(l)
        self.check(f, [int], fullopts=True, getarraysize=0)


def fakevar(name='v'):
    var = Variable(name)
    var.concretetype = "fake concrete type"
    return var

def fakeconst(val):
    const = Constant(val)
    const.concretetype = "fake concrete type"
    return const

def test_find_new_res():
    # unit test for _find_new_res

    class FakeFamilies(object):
        def find_rep(self, var):
            return reps.get(var, var)

    reps = {}
    c = Cache(FakeFamilies(), None)

    # two different vars
    v1 = fakevar()
    v2 = fakevar()
    res, needs_adding = c._find_new_res([v1, v2])
    assert needs_adding
    assert isinstance(res, Variable)
    assert res.concretetype == v1.concretetype

    # the same var
    res, needs_adding = c._find_new_res([v1, v1])
    assert not needs_adding
    assert res is v1

    # different vars, but same reps
    reps = {v2: v1}
    res, needs_adding = c._find_new_res([v1, v2])
    assert not needs_adding
    assert res is v1

    # two different consts
    c1 = fakeconst(1)
    c2 = fakeconst(2)
    res, needs_adding = c._find_new_res([c1, c2])
    assert needs_adding
    assert isinstance(res, Variable)
    assert res.concretetype == v1.concretetype

    # the same const
    c1 = fakeconst(1)
    res, needs_adding = c._find_new_res([c1, c1])
    assert not needs_adding
    assert res == c1

    # different vars, but same reps, 2
    reps = {v2: v1}
    res, needs_adding = c._find_new_res([v2, v2])
    assert not needs_adding
    assert res is v2


def test_loop_blocks():
    from rpython.flowspace.model import mkentrymap
    from rpython.translator.backendopt import support
    class A(object): pass
    def f(i):
        res = 0
        y = 0
        while y < i: # block1
            y += 1 # block2
            x = i
            a = A()
            if i == 0:
                a.x = 1 # block3
            else:
                a.x = i # block4
            while x: # block5
                x -= 1 # block6
                res += a.x
                if x % 1000 == 1:
                    a.x = 5 # block7
        return res # block8

    t = TranslationContext()
    t.buildannotator().build_types(f, [int])
    t.buildrtyper().specialize()
    graph = graphof(t, f)
    startblock = graph.startblock
    block1 = startblock.exits[0].target
    block2 = block1.exits[1].target
    block3 = block2.exits[0].target
    block4 = block2.exits[1].target
    block5 = block4.exits[0].target
    block6 = block5.exits[1].target
    block7 = block6.exits[1].target

    loops = loop_blocks(graph, support.find_backedges(graph),
                        mkentrymap(graph))
    assert loops == {
        block1: {block1, block2, block3, block4, block5, block6, block7},
        block5: {block5, block6, block7},
    }

from pypy.objspace.std.smalltupleobject import W_SmallTupleObject
from pypy.interpreter.error import OperationError
from pypy.objspace.std.test.test_tupleobject import AppTestW_TupleObject
from pypy.conftest import gettestobjspace

class AppTestW_SmallTupleObject(AppTestW_TupleObject):

    def setup_class(cls):
        cls.space = gettestobjspace(**{"objspace.std.withsmalltuple": True})

class TestW_SmallTupleObject():

    def setup_class(cls):
        cls.space = gettestobjspace(**{"objspace.std.withsmalltuple": True})

    def test_issmalltupleobject(self):
        w_tuple = self.space.newtuple([self.space.wrap(1), self.space.wrap(2)])
        assert isinstance(w_tuple, W_SmallTupleObject)

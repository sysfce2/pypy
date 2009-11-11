
from pypy.conftest import gettestobjspace

class AppTestExc(object):
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=('tempexceptions',))

    def test_baseexc(self):
        from tempexceptions import BaseException

        assert str(BaseException()) == ''
        assert repr(BaseException()) == 'BaseException()'
        assert BaseException().message == ''
        assert BaseException(3).message == 3
        assert repr(BaseException(3)) == 'BaseException(3,)'
        assert str(BaseException(3)) == '3'
        assert BaseException().args == ()
        assert BaseException(3).args == (3,)
        assert BaseException(3, "x").args == (3, "x")
        assert repr(BaseException(3, "x")) == "BaseException(3, 'x')"
        assert str(BaseException(3, "x")) == "(3, 'x')"
        assert BaseException(3, "x").message == ''

    def test_exc(self):
        from tempexceptions import Exception, BaseException

        assert issubclass(Exception, BaseException)
        assert isinstance(Exception(), Exception)
        assert isinstance(Exception(), BaseException)
        assert repr(Exception(3, "x")) == "Exception(3, 'x')"

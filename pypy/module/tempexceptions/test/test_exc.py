
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
        x = BaseException()
        x.xyz = 3
        assert x.xyz == 3

    def test_exc(self):
        from tempexceptions import Exception, BaseException

        assert issubclass(Exception, BaseException)
        assert isinstance(Exception(), Exception)
        assert isinstance(Exception(), BaseException)
        assert repr(Exception(3, "x")) == "Exception(3, 'x')"

    def test_custom_class(self):
        from tempexceptions import Exception

        class MyException(Exception):
            def __init__(self, x):
                self.x = x

            def __str__(self):
                return self.x

        assert issubclass(MyException, Exception)
        assert str(MyException("x")) == "x"

    def test_unicode_translate_error(self):
        from tempexceptions import UnicodeTranslateError
        ut = UnicodeTranslateError(u"x", 1, 5, "bah")
        assert ut.object == u'x'
        assert ut.start == 1
        assert ut.end == 5
        assert ut.reason == 'bah'
        assert ut.args == (u'x', 1, 5, 'bah')
        assert ut.message == ''
        ut.object = u'y'
        assert ut.object == u'y'
        assert str(ut) == "can't translate characters in position 1-4: bah"

    def test_key_error(self):
        from tempexceptions import KeyError

        assert str(KeyError('s')) == "'s'"

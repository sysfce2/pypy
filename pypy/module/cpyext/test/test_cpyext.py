import sys

import py

from pypy.conftest import gettestobjspace
from pypy.interpreter.error import OperationError
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.translator.tool.cbuild import ExternalCompilationInfo
from pypy.translator import platform
from pypy.module.cpyext import api
from pypy.module.cpyext.state import State
from pypy.module.cpyext.macros import Py_DECREF
from pypy.translator.goal import autopath

@api.cpython_api([], api.PyObject)
def PyPy_Crash1(space):
    1/0

@api.cpython_api([], lltype.Signed, error=-1)
def PyPy_Crash2(space):
    1/0

class TestApi:
    def test_signature(self):
        assert 'PyModule_Check' in api.FUNCTIONS
        assert api.FUNCTIONS['PyModule_Check'].argtypes == [api.PyObject]

    def test_padding(self):
        T = api.get_padded_type(api.PyObject.TO, 42)
        assert rffi.sizeof(T) == 42
        print T

class AppTestApi:
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=['cpyext'])
        from pypy.rlib.libffi import get_libc_name
        cls.w_libc = cls.space.wrap(get_libc_name())

    def test_load_error(self):
        import cpyext
        raises(ImportError, cpyext.load_module, "missing.file", "foo")
        raises(ImportError, cpyext.load_module, self.libc, "invalid.function")

def compile_module(modname, **kwds):
    eci = ExternalCompilationInfo(
        export_symbols=['init%s' % (modname,)],
        include_dirs=api.include_dirs,
        **kwds
        )
    eci = eci.convert_sources_to_files()
    soname = platform.platform.compile(
        [], eci,
        standalone=False)
    return str(soname)

class AppTestCpythonExtensionBase:
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=['cpyext'])
        cls.freeze_refcnts()

    def import_module(self, name, init=None, body=''):
        if init is not None:
            code = """
            #include <pypy_rename.h>
            #include <Python.h>
            %(body)s

            void init%(name)s(void) {
            %(init)s
            }
            """ % dict(name=name, init=init, body=body)
            kwds = dict(separate_module_sources=[code])
        else:
            filename = py.path.local(autopath.pypydir) / 'module' \
                    / 'cpyext'/ 'test' / (name + ".c")
            kwds = dict(separate_module_files=[filename])

        state = self.space.fromcache(State)
        api_library = state.api_lib
        if sys.platform == 'win32':
            kwds["libraries"] = [api_library]
        else:
            kwds["link_files"] = [str(api_library + '.so')]
            kwds["compile_extra"] = ["-Werror=implicit-function-declaration"]
        mod = compile_module(name, **kwds)

        api.load_extension_module(self.space, mod, name)
        return self.space.getitem(
            self.space.sys.get('modules'),
            self.space.wrap(name))

    def import_extension(self, modname, functions):

        methods_table = []
        codes = []
        for funcname, flags, code in functions:
            cfuncname = "%s_%s" % (modname, funcname)
            methods_table.append("{\"%s\", %s, %s}," %
                                 (funcname, cfuncname, flags))
            func_code = """
            static PyObject* %s(PyObject* self, PyObject* args)
            {
            %s
            }
            """ % (cfuncname, code)
            codes.append(func_code)

        body = "\n".join(codes) + """
        static PyMethodDef methods[] = {
        %s
        { NULL }
        };
        """ % ('\n'.join(methods_table),)
        init = """Py_InitModule("%s", methods);""" % (modname,)
        return self.import_module(name=modname, init=init, body=body)

    def setup_method(self, func):
        self.w_import_module = self.space.wrap(self.import_module)
        self.w_import_extension = self.space.wrap(self.import_extension)
        #self.check_and_print_leaks("Object %r leaked some time ago (refcount %i) -- Not executing test!")

    def teardown_method(self, func):
        try:
            w_mod = self.space.getitem(self.space.sys.get('modules'),
                               self.space.wrap('foo'))
            self.space.delitem(self.space.sys.get('modules'),
                               self.space.wrap('foo'))
            Py_DECREF(self.space, w_mod)
        except OperationError:
            pass
        if self.check_and_print_leaks():
            assert False, "Test leaks object(s)."

    @classmethod
    def freeze_refcnts(cls):
        state = cls.space.fromcache(State)
        cls.frozen_refcounts = {}
        for w_obj, obj in state.py_objects_w2r.iteritems():
            cls.frozen_refcounts[w_obj] = obj.c_obj_refcnt

    def check_and_print_leaks(self):
        # check for sane refcnts
        leaking = False
        state = self.space.fromcache(State)
        global_objects_w = set()
        for w_obj, obj in state.py_objects_w2r.iteritems():
            base_refcnt = self.frozen_refcounts.get(w_obj)
            delta = obj.c_obj_refcnt
            if base_refcnt is not None:
                delta -= base_refcnt
            if delta != 0:
                leaking = True
                print >>sys.stderr, "Leaking %r: %i references" % (w_obj, delta)
        return leaking


class AppTestCpythonExtension(AppTestCpythonExtensionBase):
    def test_createmodule(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", NULL);
        """
        self.import_module(name='foo', init=init)
        assert 'foo' in sys.modules

    def test_export_function(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        PyObject* foo_pi(PyObject* self, PyObject *args)
        {
            return PyFloat_FromDouble(3.14);
        }
        static PyMethodDef methods[] = {
            { "return_pi", foo_pi, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert 'foo' in sys.modules
        assert 'return_pi' in dir(module)
        assert module.return_pi is not None
        assert module.return_pi() == 3.14

    def test_InitModule4(self):
        init = """
        PyObject *cookie = PyFloat_FromDouble(3.14);
        Py_InitModule4("foo", methods, "docstring",
                       cookie, PYTHON_API_VERSION);
        Py_DECREF(cookie);
        """
        body = """
        PyObject* return_cookie(PyObject* self, PyObject *args)
        {
            if (self)
            {
                Py_INCREF(self);
                return self;
            }
            else
                Py_RETURN_FALSE;
        }
        static PyMethodDef methods[] = {
            { "return_cookie", return_cookie, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert module.__doc__ == "docstring"
        assert module.return_cookie() == 3.14

    def test_export_function2(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* my_objects[1];
        static PyObject* foo_cached_pi(PyObject* self, PyObject *args)
        {
            if (my_objects[0] == NULL) {
                my_objects[0] = PyFloat_FromDouble(3.14);
            }
            Py_INCREF(my_objects[0]);
            return my_objects[0];
        }
        static PyObject* foo_drop_pi(PyObject* self, PyObject *args)
        {
            if (my_objects[0] != NULL) {
                Py_DECREF(my_objects[0]);
                my_objects[0] = NULL;
            }
            Py_INCREF(Py_None);
            return Py_None;
        }
        static PyObject* foo_retinvalid(PyObject* self, PyObject *args)
        {
            return (PyObject*)0xAFFEBABE;
        }
        static PyMethodDef methods[] = {
            { "return_pi", foo_cached_pi, METH_NOARGS },
            { "drop_pi",   foo_drop_pi, METH_NOARGS },
            { "return_invalid_pointer", foo_retinvalid, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert module.return_pi() == 3.14
        print "A"
        module.drop_pi()
        print "B"
        module.drop_pi()
        print "C"
        assert module.return_pi() == 3.14
        print "D"
        assert module.return_pi() == 3.14
        print "E"
        module.drop_pi()
        skip("Hmm, how to check for the exception?")
        raises(api.InvalidPointerException, module.return_invalid_pointer)

    def test_argument(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        PyObject* foo_test(PyObject* self, PyObject *args)
        {
            return PyTuple_GetItem(args, 0);
        }
        static PyMethodDef methods[] = {
            { "test", foo_test, METH_VARARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert module.test(True, True) == True

    def test_exception(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* foo_pi(PyObject* self, PyObject *args)
        {
            PyErr_SetString(PyExc_Exception, "moo!");
            return NULL;
        }
        static PyMethodDef methods[] = {
            { "raise_exception", foo_pi, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        exc = raises(Exception, module.raise_exception)
        if type(exc.value) is not Exception:
            raise exc.value

        assert exc.value.message == "moo!"

    def test_refcount(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* foo_pi(PyObject* self, PyObject *args)
        {
            PyObject *true = Py_True;
            int refcnt = Py_REFCNT(true);
            int refcnt_after;
            Py_INCREF(true);
            Py_INCREF(true);
            PyBool_Check(true);
            refcnt_after = Py_REFCNT(true);
            Py_DECREF(true);
            Py_DECREF(true);
            fprintf(stderr, "REFCNT %i %i\\n", refcnt, refcnt_after);
            return PyBool_FromLong(refcnt_after == refcnt+2 && refcnt < 3);
        }
        static PyObject* foo_bar(PyObject* self, PyObject *args)
        {
            PyObject *true = Py_True;
            PyObject *tup = NULL;
            int refcnt = Py_REFCNT(true);
            int refcnt_after;

            tup = PyTuple_New(1);
            Py_INCREF(true);
            if (PyTuple_SetItem(tup, 0, true) < 0)
                return NULL;
            refcnt_after = Py_REFCNT(true);
            Py_DECREF(tup);
            fprintf(stderr, "REFCNT2 %i %i\\n", refcnt, refcnt_after);
            return PyBool_FromLong(refcnt_after == refcnt);
        }

        static PyMethodDef methods[] = {
            { "test_refcount", foo_pi, METH_NOARGS },
            { "test_refcount2", foo_bar, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert module.test_refcount()
        assert module.test_refcount2()


    def test_init_exception(self):
        import sys
        init = """
            PyErr_SetString(PyExc_Exception, "moo!");
        """
        exc = raises(Exception, "self.import_module(name='foo', init=init)")
        if type(exc.value) is not Exception:
            raise exc.value

        assert exc.value.message == "moo!"


    def test_internal_exceptions(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        PyObject* PyPy_Crash1(void);
        long PyPy_Crash2(void);
        static PyObject* foo_crash1(PyObject* self, PyObject *args)
        {
            return PyPy_Crash1();
        }
        static PyObject* foo_crash2(PyObject* self, PyObject *args)
        {
            int a = PyPy_Crash2();
            if (a == -1)
                return NULL;
            return PyFloat_FromDouble(a);
        }
        static PyObject* foo_crash3(PyObject* self, PyObject *args)
        {
            int a = PyPy_Crash2();
            if (a == -1)
                PyErr_Clear();
            return PyFloat_FromDouble(a);
        }
        static PyObject* foo_crash4(PyObject* self, PyObject *args)
        {
            int a = PyPy_Crash2();
            return PyFloat_FromDouble(a);
        }
        static PyObject* foo_clear(PyObject* self, PyObject *args)
        {
            PyErr_Clear();
            return NULL;
        }
        static PyMethodDef methods[] = {
            { "crash1", foo_crash1, METH_NOARGS },
            { "crash2", foo_crash2, METH_NOARGS },
            { "crash3", foo_crash3, METH_NOARGS },
            { "crash4", foo_crash4, METH_NOARGS },
            { "clear",  foo_clear, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        # uncaught interplevel exceptions are turned into SystemError
        raises(SystemError, module.crash1)
        raises(SystemError, module.crash2)
        # caught exception
        assert module.crash3() == -1
        # An exception was set, but function returned a value
        raises(SystemError, module.crash4)
        # No exception set, but NULL returned
        raises(SystemError, module.clear)



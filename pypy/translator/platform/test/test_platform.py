
import py, sys, ctypes
from pypy.tool.udir import udir
from pypy.translator.platform import CompilationError, Platform
from pypy.translator.platform import host
from pypy.translator.tool.cbuild import ExternalCompilationInfo

class TestPlatform(object):
    platform = host
    strict_on_stderr = True
    
    def check_res(self, res, expected='42\n'):
        assert res.out == expected
        if self.strict_on_stderr:
            assert res.err == ''
        assert res.returncode == 0        
    
    def test_simple_enough(self):
        cfile = udir.join('test_simple_enough.c')
        cfile.write('''
        #include <stdio.h>
        int main()
        {
            printf("42\\n");
            return 0;
        }
        ''')
        executable = self.platform.compile([cfile], ExternalCompilationInfo())
        res = self.platform.execute(executable)
        self.check_res(res)

    def test_two_files(self):
        cfile = udir.join('test_two_files.c')
        cfile.write('''
        #include <stdio.h>
        int func();
        int main()
        {
            printf("%d\\n", func());
            return 0;
        }
        ''')
        cfile2 = udir.join('implement1.c')
        cfile2.write('''
        int func()
        {
            return 42;
        }
        ''')
        executable = self.platform.compile([cfile, cfile2], ExternalCompilationInfo())
        res = self.platform.execute(executable)
        self.check_res(res)

    def test_nice_errors(self):
        cfile = udir.join('test_nice_errors.c')
        cfile.write('')
        try:
            executable = self.platform.compile([cfile], ExternalCompilationInfo())
        except CompilationError, e:
            filename = cfile.dirpath().join(cfile.purebasename + '.errors')
            assert filename.read('r') == e.err
        else:
            py.test.fail("Did not raise")

    def test_use_eci(self):
        tmpdir = udir.join('use_eci').ensure(dir=1)
        hfile = tmpdir.join('needed.h')
        hfile.write('#define SOMEHASHDEFINE 42\n')
        eci = ExternalCompilationInfo(include_dirs=[tmpdir])
        cfile = udir.join('use_eci_c.c')
        cfile.write('''
        #include <stdio.h>
        #include "needed.h"
        int main()
        {
            printf("%d\\n", SOMEHASHDEFINE);
            return 0;
        }
        ''')
        executable = self.platform.compile([cfile], eci)
        res = self.platform.execute(executable)
        self.check_res(res)

    def test_standalone_library(self):
        tmpdir = udir.join('standalone_library').ensure(dir=1)
        c_file = tmpdir.join('stand1.c')
        c_file.write('''
        #include <math.h>
        #include <stdio.h>

        int main()
        {
            printf("%f\\n", pow(2.0, 2.0));
        }''')
        if sys.platform != 'win32':
            eci = ExternalCompilationInfo(
                libraries = ['m'],
                )
        else:
            eci = ExternalCompilationInfo()
        executable = self.platform.compile([c_file], eci)
        res = self.platform.execute(executable)
        assert res.out.startswith('4.0')

def test_equality():
    class X(Platform):
        def __init__(self):
            pass
    class Y(Platform):
        def __init__(self, x):
            self.x = x

    assert X() == X()
    assert Y(3) == Y(3)
    assert Y(2) != Y(3)

#include "common_header.h"
#ifdef PYPY_STANDALONE
#include "structdef.h"
#include "forwarddecl.h"
#include "preimpl.h"
#include <src/entrypoint.h>
#include <src/commondefs.h>
#include <src/mem.h>
#include <src/instrument.h>
#include <src/rtyper.h>
#include <src/exception.h>
#include <src/debug_traceback.h>
#include <src/asm.h>

#include <stdlib.h>
#include <stdio.h>


#if defined(MS_WINDOWS)
#  include <stdio.h>
#  include <fcntl.h>
#  include <io.h>
#  include <shlwapi.h>
#  include <string.h>
#  include <malloc.h>
#  include <libloaderapi.h>
#endif

#ifdef RPY_WITH_GIL
# include <src/thread.h>
# include <src/threadlocal.h>
#endif

#ifdef RPY_REVERSE_DEBUGGER
# include <src-revdb/revdb_include.h>
#endif

char *CondaEcosystemGetWarnings();

RPY_EXPORTED
void rpython_startup_code(void)
{
#ifdef RPY_WITH_GIL
    RPython_ThreadLocals_ProgramInit();
    RPyGilAcquire();
#endif
    RPython_StartupCode();
#ifdef RPY_WITH_GIL
    RPyGilRelease();
#endif
}

#ifdef MS_WINDOWS
/* Please do not remove this function. It is needed for testing
   CondaEcosystemModifyDllSearchPath(). */

/*
void LoadAndUnloadTestDLL(wchar_t* test_dll)
{
    wchar_t test_path[MAX_PATH + 1];
    HMODULE hDLL = LoadLibraryExW(&test_dll[0], NULL, 0);
    if (hDLL == NULL)
    {
        wchar_t err_msg[256];
        DWORD err_code = GetLastError();
        FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
            NULL, err_code, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
            err_msg, (sizeof(err_msg) / sizeof(wchar_t)), NULL);
        fwprintf(stderr, L"LoadAndUnloadTestDLL() :: ERROR :: Failed to load %ls, error is: %ls\n", &test_dll[0], &err_msg[0]);
    }
    GetModuleFileNameW(hDLL, &test_path[0], MAX_PATH);
    fwprintf(stderr, L"LoadAndUnloadTestDLL() :: %ls loaded from %ls\n", &test_dll[0], &test_path[0]);
    if (FreeLibrary(hDLL) == 0)
    {
        wchar_t err_msg[256];
        DWORD err_code = GetLastError();
        FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
            NULL, err_code, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
            err_msg, (sizeof(err_msg) / sizeof(wchar_t)), NULL);
        fwprintf(stderr, L"LoadAndUnloadTestDLL() :: ERROR :: Failed to free %ls, error is: %ls\n", &test_dll[0], &err_msg[0]);
    }
}
*/

/*
    Provided CONDA_DLL_SEARCH_MODIFICATION_ENABLE is set (to anything at all!)
    this function will modify the DLL search path so that C:\Windows\System32
    does not appear before entries in PATH. If it does appear in PATH then it
    gets added at the position it was in in PATH.

    This is achieved via a call to SetDefaultDllDirectories() then calls to
    AddDllDirectory() for each entry in PATH. We also take the opportunity to
    clean-up these PATH entries such that any '/' are replaced with '\', no
    double quotes occour and no PATH entry ends with '\'.

    Caution: Microsoft's documentation says that the search order of entries
    passed to AddDllDirectory is not respected and arbitrary. I do not think
    this will be the case but it is worth bearing in mind.
*/

#if !defined(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)
#define LOAD_LIBRARY_SEARCH_DEFAULT_DIRS 0x00001000
#endif

/* Caching of prior processed PATH environment */
static wchar_t *sv_path_env = NULL;
typedef void (WINAPI *SDDD)(DWORD DirectoryFlags);
typedef void (WINAPI *SDD)(PCWSTR SetDir);
typedef void (WINAPI *ADD)(PCWSTR NewDirectory);
static SDDD pSetDefaultDllDirectories = NULL;
static SDD pSetDllDirectory = NULL;
static ADD pAddDllDirectory = NULL;
static int sv_failed_to_find_dll_fns = 0;
static int sv_conda_not_activated = 0;
/* sv_executable_dirname is gotten but not used ATM. */
static wchar_t sv_executable_dirname[1024];
/* Have hidden this behind a define because it is clearly not code that
   could be considered for upstreaming so clearly delimiting it makes it
   easier to remove. */
#define HARDCODE_CONDA_PATHS
#if defined(HARDCODE_CONDA_PATHS)
typedef struct
{
    wchar_t *p_relative;
    wchar_t *p_name;
} CONDA_PATH;

#define NUM_CONDA_PATHS 5

static CONDA_PATH condaPaths[NUM_CONDA_PATHS] =
{
    {L"Library\\mingw-w64\\bin", NULL},
    {L"Library\\usr\\bin", NULL},
    {L"Library\\bin", NULL},
    {L"Scripts", NULL},
    {L"bin", NULL}
};
#endif /* HARDCODE_CONDA_PATHS */
static wchar_t sv_executable_dirname[1024];
static wchar_t sv_windows_directory[1024];
static wchar_t *sv_added_windows_directory = NULL;
static wchar_t *sv_added_cwd = NULL;

int CondaEcosystemModifyDllSearchPath_Init(int argc, char *argv[])
{
    int debug_it = _wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_DEBUG") ? 1 : 0;
    int res = 0;
#if defined(HARDCODE_CONDA_PATHS)
    CONDA_PATH *p_conda_path;
#endif /* defined(HARDCODE_CONDA_PATHS) */

    if (pSetDefaultDllDirectories == NULL)
    {
        wchar_t *conda_prefix = _wgetenv(L"CONDA_PREFIX");
        wchar_t *build_prefix = _wgetenv(L"BUILD_PREFIX");
        wchar_t *prefix = _wgetenv(L"PREFIX");
        pSetDefaultDllDirectories = (SDDD)GetProcAddress(GetModuleHandle(TEXT("kernel32.dll")), "SetDefaultDllDirectories");
        pSetDllDirectory = (SDD)GetProcAddress(GetModuleHandle(TEXT("kernel32.dll")), "SetDllDirectoryW");
        pAddDllDirectory = (ADD)GetProcAddress(GetModuleHandle(TEXT("kernel32.dll")), "AddDllDirectory");

        /* Determine sv_executable_dirname */
        GetModuleFileNameW(NULL, &sv_executable_dirname[0], sizeof(sv_executable_dirname)/sizeof(sv_executable_dirname[0])-1);
        sv_executable_dirname[sizeof(sv_executable_dirname)/sizeof(sv_executable_dirname[0])-1] = L'\0';
        if (wcsrchr(sv_executable_dirname, L'\\'))
            *wcsrchr(sv_executable_dirname, L'\\') = L'\0';
#if defined(HARDCODE_CONDA_PATHS)
        for (p_conda_path = &condaPaths[0]; p_conda_path < &condaPaths[NUM_CONDA_PATHS]; ++p_conda_path)
        {
            size_t n_chars_executable_dirname = wcslen(sv_executable_dirname);
            size_t n_chars_p_relative = wcslen(p_conda_path->p_relative);
            p_conda_path->p_name = malloc(sizeof(wchar_t) * (n_chars_executable_dirname + n_chars_p_relative + 2));
            wcsncpy(p_conda_path->p_name, sv_executable_dirname, n_chars_executable_dirname+1);
            wcsncat(p_conda_path->p_name, L"\\", 2);
            wcsncat(p_conda_path->p_name, p_conda_path->p_relative, n_chars_p_relative+1);
        }
#endif /* defined(HARDCODE_CONDA_PATHS) */

        /* Determine sv_windows_directory */
        {
            char tmp_ascii[1024];
            size_t convertedChars = 0;
            GetWindowsDirectory(&tmp_ascii[0], sizeof(tmp_ascii) / sizeof(tmp_ascii[0]) - 1);
            tmp_ascii[sizeof(tmp_ascii) / sizeof(tmp_ascii[0]) - 1] = L'\0';
            mbstowcs_s(&convertedChars, sv_windows_directory, strlen(tmp_ascii)+1, tmp_ascii, _TRUNCATE);
            sv_windows_directory[sizeof(sv_windows_directory) / sizeof(sv_windows_directory[0]) - 1] = L'\0';
        }

        if (conda_prefix == NULL || wcscmp(sv_executable_dirname, conda_prefix))
        {
            if (build_prefix == NULL || wcscmp(sv_executable_dirname, build_prefix))
            {
                if (prefix == NULL || wcscmp(sv_executable_dirname, prefix))
                {
                    int found_conda = 0;
                    int argi;
                    /* If any of the args contain 'conda' .. I am very sorry and there's probably a better way. */
                    for (argi = 1; argi < argc; ++argi)
                    {
                        if (strcmp(argv[argi], "conda") == 0)
                        {
                            found_conda = 1;
                            break;
                        }
                    }
                    if (found_conda == 0)
                    {
                        sv_conda_not_activated = 1;
                        res = 1;
                    }
                }
            }
        }
    }

    if (pSetDefaultDllDirectories == NULL || pSetDllDirectory == NULL || pAddDllDirectory == NULL)
    {
        if (debug_it)
            fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: WARNING :: Please install KB2533623 from http://go.microsoft.com/fwlink/p/?linkid=217865\n"\
                             L"CondaEcosystemModifyDllSearchPath() :: WARNING :: to improve conda ecosystem DLL isolation");
        sv_failed_to_find_dll_fns = 1;
        res = 2;
    }
    return res;
}

char* CondaEcosystemGetWarnings()
{
    static char warnings[1024] = { 0 };
    if (sv_conda_not_activated == 1 && warnings[0] == '\0')
    {
        sprintf(warnings, "\n"
                          "Warning:\n"
                          "This Python interpreter is in a conda environment, but the environment has\n"
                          "not been activated.  Libraries may fail to load.  To activate this environment\n"
                          "please see https://conda.io/activation\n"
                          "\n");
    }
    return &warnings[0];
}

int CondaEcosystemModifyDllSearchPath(int add_windows_directory, int add_cwd) {
    int debug_it = _wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_DEBUG") ? 1 : 0;
    const wchar_t *path_env = _wgetenv(L"PATH");
    wchar_t current_working_directory[1024];
    const wchar_t *p_cwd = NULL;
    ssize_t entry_num = 0;
    ssize_t i;
    wchar_t **path_entries;
    wchar_t *path_end;
    ssize_t num_entries = 1;
#if defined(HARDCODE_CONDA_PATHS)
    ssize_t j;
    CONDA_PATH *p_conda_path;
    int foundCondaPath[NUM_CONDA_PATHS] = {0, 0, 0, 0, 0};
#endif /* defined(HARDCODE_CONDA_PATHS) */

    int SetDllDirectoryValue = LOAD_LIBRARY_SEARCH_DEFAULT_DIRS;
    if (sv_failed_to_find_dll_fns)
        return 1;

    if (_wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_ENABLE") == NULL)
        return 0;
    if (_wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_NEVER_ADD_WINDOWS_DIRECTORY"))
        add_windows_directory = 0;
    if (_wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_NEVER_ADD_CWD"))
        add_cwd = 0;

    if (add_cwd)
    {
        _wgetcwd(&current_working_directory[0], (sizeof(current_working_directory)/sizeof(current_working_directory[0])) - 1);
        current_working_directory[sizeof(current_working_directory)/sizeof(current_working_directory[0]) - 1] = L'\0';
        p_cwd = &current_working_directory[0];
    }

    /* cache path to avoid multiple adds */
    if (sv_path_env != NULL && path_env != NULL && !wcscmp(path_env, sv_path_env))
    {
        if ((add_windows_directory && sv_added_windows_directory != NULL) ||
            (!add_windows_directory && sv_added_windows_directory == NULL) )
        {
            if ((p_cwd == NULL && sv_added_cwd == NULL) ||
                p_cwd != NULL && sv_added_cwd != NULL && !wcscmp(p_cwd, sv_added_cwd))
            {
                if (_wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_NEVER_CACHE") == NULL)
                {
                    if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: INFO :: Values unchanged\n");
                    return 0;
                }
            }
        }
    }
    /* Something has changed.
       Reset to default search order */
    pSetDllDirectory(NULL);

    if (sv_path_env != NULL)
    {
        free(sv_path_env);
    }
    sv_path_env = (path_env == NULL) ? NULL : _wcsdup(path_env);

    if (path_env != NULL)
    {
        size_t len = wcslen(path_env);
        wchar_t *path = (wchar_t *)alloca((len + 1) * sizeof(wchar_t));
        if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: PATH=%ls\n\b", path_env);
        memcpy(path, path_env, (len + 1) * sizeof(wchar_t));
        /* Convert any / to \ */
        /* Replace slash with backslash */
        while ((path_end = wcschr(path, L'/')))
            *path_end = L'\\';
        /* Remove all double quotes */
        while ((path_end = wcschr(path, L'"')))
            memmove(path_end, path_end + 1, sizeof(wchar_t) * (len-- - (path_end - path)));
        /* Remove all leading and double ';' */
        while (*path == L';')
            memmove(path, path + 1, sizeof(wchar_t) * len--);
        while ((path_end = wcsstr(path, L";;")))
            memmove(path_end, path_end + 1, sizeof(wchar_t) * (len-- - (path_end - path)));
        /* Remove trailing ;'s */
        while(path[len-1] == L';')
            path[len-- - 1] = L'\0';

        if (len == 0)
            return 2;

        /* Count the number of path entries */
        path_end = path;
        while ((path_end = wcschr(path_end, L';')))
        {
            ++num_entries;
            ++path_end;
        }

        path_entries = (wchar_t **)alloca((num_entries) * sizeof(wchar_t *));
        path_end = wcschr(path, L';');

        if (getenv("CONDA_DLL_SET_DLL_DIRECTORY_VALUE") != NULL)
            SetDllDirectoryValue = atoi(getenv("CONDA_DLL_SET_DLL_DIRECTORY_VALUE"));
        pSetDefaultDllDirectories(SetDllDirectoryValue);
        while (path != NULL)
        {
            if (path_end != NULL)
            {
                *path_end = L'\0';
                /* Hygiene, no \ at the end */
                while (path_end > path && path_end[-1] == L'\\')
                {
                    --path_end;
                    *path_end = L'\0';
                }
            }
            if (wcslen(path) != 0)
                path_entries[entry_num++] = path;
            path = path_end;
            if (path != NULL)
            {
                while (*path == L'\0')
                    ++path;
                path_end = wcschr(path, L';');
            }
        }
        for (i = num_entries - 1; i > -1; --i)
        {
#if defined(HARDCODE_CONDA_PATHS)
            for (j = 0, p_conda_path = &condaPaths[0]; p_conda_path < &condaPaths[NUM_CONDA_PATHS]; ++j, ++p_conda_path)
            {
                if (!foundCondaPath[j] && !wcscmp(path_entries[i], p_conda_path->p_name))
                {
                    foundCondaPath[j] = 1;
                    break;
                }
            }
#endif /* defined(HARDCODE_CONDA_PATHS) */
            if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: AddDllDirectory(%ls)\n", path_entries[i]);
            pAddDllDirectory(path_entries[i]);
        }
    }

#if defined(HARDCODE_CONDA_PATHS)
    if (_wgetenv(L"CONDA_DLL_SEARCH_MODIFICATION_DO_NOT_ADD_EXEPREFIX") == NULL)
    {
        for (j = NUM_CONDA_PATHS-1, p_conda_path = &condaPaths[NUM_CONDA_PATHS-1]; j > -1; --j, --p_conda_path)
        {
            if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: p_conda_path->p_name = %ls, foundCondaPath[%zd] = %d\n", p_conda_path->p_name, j, foundCondaPath[j]);
            if (!foundCondaPath[j])
            {
                if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: AddDllDirectory(%ls - ExePrefix)\n", p_conda_path->p_name);
                pAddDllDirectory(p_conda_path->p_name);
            }
        }
    }
#endif /* defined(HARDCODE_CONDA_PATHS) */

    if (p_cwd)
    {
        if (sv_added_cwd != NULL && wcscmp(p_cwd, sv_added_cwd))
        {
            free(sv_added_cwd);
        }
        sv_added_cwd = _wcsdup(p_cwd);
        if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: AddDllDirectory(%ls - CWD)\n", sv_added_cwd);
        pAddDllDirectory(sv_added_cwd);
    }

    if (add_windows_directory)
    {
        sv_added_windows_directory = &sv_windows_directory[0];
        if (debug_it) fwprintf(stderr, L"CondaEcosystemModifyDllSearchPath() :: AddDllDirectory(%ls - WinDir)\n", sv_windows_directory);
        pAddDllDirectory(sv_windows_directory);
    }
    else
    {
        sv_added_windows_directory = NULL;
    }

    return 0;
}
#else
char* CondaEcosystemGetWarnings()
{
    return "";
}
#endif

RPY_EXTERN
int pypy_main_function(int argc, char *argv[])
{
    char *errmsg;
    int i, exitcode;

#if defined(MS_WINDOWS)
    _setmode(0, _O_BINARY);
    _setmode(1, _O_BINARY);
    _setmode(2, _O_BINARY);
    /* LoadAndUnloadTestDLL(L"libiomp5md.dll"); */
    CondaEcosystemModifyDllSearchPath_Init(argc, argv);
    /* LoadAndUnloadTestDLL(L"libiomp5md.dll"); */
#endif

#ifdef RPY_WITH_GIL
    /* Note that the GIL's mutexes are not automatically made; if the
       program starts threads, it needs to call rgil.gil_allocate().
       RPyGilAcquire() still works without that, but crash if it finds
       that it really needs to wait on a mutex. */
    RPython_ThreadLocals_ProgramInit();
    RPyGilAcquire();
#endif

    instrument_setup();

#ifdef RPY_REVERSE_DEBUGGER
    rpy_reverse_db_setup(&argc, &argv);
#endif

#ifndef MS_WINDOWS
    /* this message does no longer apply to win64 :-) */
    if (sizeof(void*) != SIZEOF_LONG) {
        errmsg = "only support platforms where sizeof(void*) == sizeof(long),"
                 " for now";
        goto error;
    }
#endif

    RPython_StartupCode();

#ifndef RPY_REVERSE_DEBUGGER
    exitcode = STANDALONE_ENTRY_POINT(argc, argv);
#else
    exitcode = rpy_reverse_db_main(STANDALONE_ENTRY_POINT, argc, argv);
#endif

    pypy_debug_alloc_results();

    if (RPyExceptionOccurred()) {
        /* print the RPython traceback */
        pypy_debug_catch_fatal_exception();
    }

    pypy_malloc_counters_results();

#ifdef RPY_WITH_GIL
    RPyGilRelease();
#endif

    return exitcode;

 memory_out:
    errmsg = "out of memory";
 error:
    fprintf(stderr, "Fatal error during initialization: %s\n", errmsg);
    abort();
    return 1;
}

int PYPY_MAIN_FUNCTION(int argc, char *argv[])
{
#ifdef PYPY_X86_CHECK_SSE2_DEFINED
    pypy_x86_check_sse2();
#endif
    return pypy_main_function(argc, argv);
}

#endif  /* PYPY_STANDALONE */

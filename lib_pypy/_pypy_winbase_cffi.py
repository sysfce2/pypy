# auto-generated file
import _cffi_backend

ffi = _cffi_backend.FFI('_pypy_winbase_cffi',
    _version = 0x2601,
    _types = b'\x00\x00\x01\x0D\x00\x00\x07\x01\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\x09\x01\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\x19\x01\x00\x00\x07\x01\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\xF0\x03\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x13\x03\x00\x00\xE3\x03\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\x00\x0F\x00\x00\x01\x0D\x00\x00\xEA\x03\x00\x00\x1A\x11\x00\x00\x11\x11\x00\x00\x11\x11\x00\x00\x07\x01\x00\x00\x0A\x01\x00\x00\x1A\x11\x00\x00\x1A\x11\x00\x00\xE8\x03\x00\x00\xE4\x03\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x03\x00\x00\x26\x11\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x26\x11\x00\x00\x11\x11\x00\x00\xDF\x03\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x15\x11\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x15\x11\x00\x00\x14\x11\x00\x00\x07\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x15\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\xE9\x03\x00\x00\x0A\x01\x00\x00\x14\x11\x00\x00\x14\x11\x00\x00\x15\x11\x00\x00\xDA\x03\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x08\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x14\x11\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x14\x11\x00\x00\x14\x03\x00\x00\x15\x03\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x14\x11\x00\x00\x14\x11\x00\x00\x14\x11\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x15\x11\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x11\x11\x00\x00\x11\x11\x00\x00\x11\x11\x00\x00\x26\x11\x00\x00\x0A\x01\x00\x00\x07\x01\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x01\x0D\x00\x00\x96\x03\x00\x00\x74\x11\x00\x00\x11\x11\x00\x00\x11\x11\x00\x00\x07\x01\x00\x00\x0A\x01\x00\x00\x74\x11\x00\x00\x74\x11\x00\x00\x22\x11\x00\x00\x23\x11\x00\x00\x02\x0F\x00\x00\x0D\x0D\x00\x00\x07\x01\x00\x00\x00\x0F\x00\x00\x51\x0D\x00\x00\x08\x01\x00\x00\x02\x0F\x00\x00\x13\x0D\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x13\x0D\x00\x00\x11\x11\x00\x00\x74\x11\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x13\x0D\x00\x00\x02\x0F\x00\x00\x91\x0D\x00\x00\x06\x01\x00\x00\x00\x0F\x00\x00\x91\x0D\x00\x00\x00\x0F\x00\x00\x91\x0D\x00\x00\x10\x01\x00\x00\x00\x0F\x00\x00\x11\x0D\x00\x00\xE7\x03\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\xEA\x03\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x99\x11\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\x96\x03\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x9C\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x99\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x11\x11\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x9C\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x99\x11\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\x07\x01\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x11\x11\x00\x00\x11\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\x74\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x99\x11\x00\x00\x02\x0F\x00\x00\x11\x0D\x00\x00\xA2\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x99\x11\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x11\x11\x00\x00\x02\x0F\x00\x00\xF0\x0D\x00\x00\x0A\x01\x00\x00\x0A\x01\x00\x00\x11\x11\x00\x00\x00\x0F\x00\x00\xF0\x0D\x00\x00\x11\x11\x00\x00\x07\x01\x00\x00\x02\x0F\x00\x00\x04\x09\x00\x00\x02\x09\x00\x00\xE6\x03\x00\x00\x05\x09\x00\x00\x06\x09\x00\x00\x03\x09\x00\x00\x07\x09\x00\x00\x02\x01\x00\x00\x40\x03\x00\x00\x01\x09\x00\x00\x00\x09\x00\x00\xEF\x03\x00\x00\x04\x01\x00\x00\x00\x01',
    _globals = (b'\x00\x00\x33\x23CancelIo',0,b'\x00\x00\x36\x23CancelIoEx',0,b'\x00\x00\x33\x23CloseHandle',0,b'\x00\x00\x36\x23ConnectNamedPipe',0,b'\x00\x00\x98\x23CreateEventA',0,b'\x00\x00\x9E\x23CreateEventW',0,b'\x00\x00\xA4\x23CreateFileA',0,b'\x00\x00\xD1\x23CreateFileW',0,b'\x00\x00\xBF\x23CreateIoCompletionPort',0,b'\x00\x00\xAD\x23CreateNamedPipeA',0,b'\x00\x00\xC7\x23CreateNamedPipeW',0,b'\x00\x00\x25\x23CreatePipe',0,b'\x00\x00\x19\x23CreateProcessA',0,b'\x00\x00\x73\x23CreateProcessW',0,b'\x00\x00\x6A\x23DuplicateHandle',0,b'\x00\x00\xC5\x23GetCurrentProcess',0,b'\x00\x00\x53\x23GetExitCodeProcess',0,b'\x00\x00\x8E\x23GetLastError',0,b'\x00\x00\x89\x23GetModuleFileNameW',0,b'\x00\x00\x3A\x23GetOverlappedResult',0,b'\x00\x00\x57\x23GetQueuedCompletionStatus',0,b'\x00\x00\xBC\x23GetStdHandle',0,b'\x00\x00\x8E\x23GetVersion',0,b'\x00\x00\x64\x23PostQueuedCompletionStatus',0,b'\x00\x00\x10\x23ReadFile',0,b'\x00\x00\x2B\x23RegisterWaitForSingleObject',0,b'\xFF\xFF\xFF\x1FSEM_FAILCRITICALERRORS',1,b'\xFF\xFF\xFF\x1FSEM_NOALIGNMENTFAULTEXCEPT',4,b'\xFF\xFF\xFF\x1FSEM_NOGPFAULTERRORBOX',2,b'\xFF\xFF\xFF\x1FSEM_NOOPENFILEERRORBOX',32768,b'\x00\x00\x82\x23SetErrorMode',0,b'\x00\x00\x33\x23SetEvent',0,b'\x00\x00\x5E\x23SetNamedPipeHandleState',0,b'\x00\x00\x4F\x23TerminateProcess',0,b'\x00\x00\x46\x23WSARecv',0,b'\xFF\xFF\xFF\x1FWT_EXECUTEINWAITTHREAD',4,b'\xFF\xFF\xFF\x1FWT_EXECUTEONLYONCE',8,b'\x00\x00\x85\x23WaitForSingleObject',0,b'\x00\x00\x7F\x23_get_osfhandle',0,b'\x00\x00\x17\x23_getch',0,b'\x00\x00\x17\x23_getche',0,b'\x00\x00\x93\x23_getwch',0,b'\x00\x00\x93\x23_getwche',0,b'\x00\x00\x17\x23_kbhit',0,b'\x00\x00\x07\x23_locking',0,b'\x00\x00\x0C\x23_open_osfhandle',0,b'\x00\x00\x00\x23_putch',0,b'\x00\x00\x95\x23_putwch',0,b'\x00\x00\x03\x23_setmode',0,b'\x00\x00\x00\x23_ungetch',0,b'\x00\x00\x90\x23_ungetwch',0,b'\x00\x00\xB7\x23socket',0),
    _struct_unions = ((b'\x00\x00\x00\xED\x00\x00\x00\x03$1',b'\x00\x00\xEC\x11DUMMYSTRUCTNAME',b'\x00\x00\x11\x11Pointer'),(b'\x00\x00\x00\xEC\x00\x00\x00\x02$2',b'\x00\x00\x13\x11Offset',b'\x00\x00\x13\x11OffsetHigh'),(b'\x00\x00\x00\xE4\x00\x00\x00\x02$PROCESS_INFORMATION',b'\x00\x00\x11\x11hProcess',b'\x00\x00\x11\x11hThread',b'\x00\x00\x13\x11dwProcessId',b'\x00\x00\x13\x11dwThreadId'),(b'\x00\x00\x00\xE8\x00\x00\x00\x02$STARTUPINFO',b'\x00\x00\x13\x11cb',b'\x00\x00\x1A\x11lpReserved',b'\x00\x00\x1A\x11lpDesktop',b'\x00\x00\x1A\x11lpTitle',b'\x00\x00\x13\x11dwX',b'\x00\x00\x13\x11dwY',b'\x00\x00\x13\x11dwXSize',b'\x00\x00\x13\x11dwYSize',b'\x00\x00\x13\x11dwXCountChars',b'\x00\x00\x13\x11dwYCountChars',b'\x00\x00\x13\x11dwFillAttribute',b'\x00\x00\x13\x11dwFlags',b'\x00\x00\x91\x11wShowWindow',b'\x00\x00\x91\x11cbReserved2',b'\x00\x00\xEE\x11lpReserved2',b'\x00\x00\x11\x11hStdInput',b'\x00\x00\x11\x11hStdOutput',b'\x00\x00\x11\x11hStdError'),(b'\x00\x00\x00\xE3\x00\x00\x00\x02_OVERLAPPED',b'\x00\x00\x13\x11Internal',b'\x00\x00\x13\x11InternalHigh',b'\x00\x00\xED\x11DUMMYUNIONNAME',b'\x00\x00\x11\x11hEvent'),(b'\x00\x00\x00\xE6\x00\x00\x00\x02_PostCallbackData',b'\x00\x00\x11\x11hCompletionPort',b'\x00\x00\x15\x11Overlapped'),(b'\x00\x00\x00\xE7\x00\x00\x00\x02_SECURITY_ATTRIBUTES',b'\x00\x00\x13\x11nLength',b'\x00\x00\x11\x11lpSecurityDescriptor',b'\x00\x00\x01\x11bInheritHandle'),(b'\x00\x00\x00\xE9\x00\x00\x00\x02_WSABUF',b'\x00\x00\x13\x11len',b'\x00\x00\x1A\x11buf')),
    _typenames = (b'\x00\x00\x00\xEBLPFN_DISCONNECTEX',b'\x00\x00\x00\x15LPOVERLAPPED',b'\x00\x00\x00\x4DLPOVERLAPPED_COMPLETION_ROUTINE',b'\x00\x00\x00\x23LPPROCESS_INFORMATION',b'\x00\x00\x00\xE5LPPostCallbackData',b'\x00\x00\x00\x99LPSECURITY_ATTRIBUTES',b'\x00\x00\x00\x22LPSTARTUPINFO',b'\x00\x00\x00\x48LPWSABUF',b'\x00\x00\x00\xE3OVERLAPPED',b'\x00\x00\x00\xE4PROCESS_INFORMATION',b'\x00\x00\x00\x99PSECURITY_ATTRIBUTES',b'\x00\x00\x00\xE6PostCallbackData',b'\x00\x00\x00\xE7SECURITY_ATTRIBUTES',b'\x00\x00\x00\x11SOCKET',b'\x00\x00\x00\xE8STARTUPINFO',b'\x00\x00\x00\x2EWAITORTIMERCALLBACK',b'\x00\x00\x00\xE9WSABUF',b'\x00\x00\x00\x91wint_t'),
)

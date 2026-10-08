"""Create llama suspended, assign it to a kill-on-close job, then resume.

No console window; no unrelated process is ever terminated. The job handle is
not inheritable, so a crashed owner closes its last handle. Only diagnostics
and NUL input handles are made inheritable during process creation.
"""
import ctypes as ct
from ctypes import wintypes as wt
import os
import msvcrt
import subprocess
import threading
import sys

if os.name != 'nt':
    raise RuntimeError('This desktop application requires Windows.')

kernel = ct.WinDLL('kernel32', use_last_error=True)
SIZE_T = ct.c_size_t
ULONG_PTR = ct.c_size_t


class BASIC_LIMIT(ct.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ct.c_int64), ('PerJobUserTimeLimit', ct.c_int64),
                ('LimitFlags', wt.DWORD), ('MinimumWorkingSetSize', SIZE_T),
                ('MaximumWorkingSetSize', SIZE_T), ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ULONG_PTR), ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class IO_COUNTERS(ct.Structure):
    _fields_ = [(name, ct.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
                 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class EXTENDED_LIMIT(ct.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', SIZE_T), ('JobMemoryLimit', SIZE_T),
                ('PeakProcessMemoryUsed', SIZE_T), ('PeakJobMemoryUsed', SIZE_T)]


class STARTUPINFO(ct.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
                ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
                ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
                ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                ('lpReserved2', ct.POINTER(ct.c_byte)), ('hStdInput', wt.HANDLE),
                ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class PROCESSINFO(ct.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


def bind(name, args, result=wt.BOOL):
    func = getattr(kernel, name)
    func.argtypes, func.restype = args, result
    return func


CreateJob = bind('CreateJobObjectW', [ct.c_void_p, wt.LPCWSTR], wt.HANDLE)
SetJob = bind('SetInformationJobObject', [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD])
AssignJob = bind('AssignProcessToJobObject', [wt.HANDLE, wt.HANDLE])
CreateProcess = bind('CreateProcessW', [wt.LPCWSTR, wt.LPWSTR, ct.c_void_p, ct.c_void_p,
                     wt.BOOL, wt.DWORD, ct.c_void_p, wt.LPCWSTR,
                     ct.POINTER(STARTUPINFO), ct.POINTER(PROCESSINFO)])
ResumeThread = bind('ResumeThread', [wt.HANDLE], wt.DWORD)
Wait = bind('WaitForSingleObject', [wt.HANDLE, wt.DWORD], wt.DWORD)
GetExit = bind('GetExitCodeProcess', [wt.HANDLE, ct.POINTER(wt.DWORD)])
Terminate = bind('TerminateProcess', [wt.HANDLE, wt.UINT])
Close = bind('CloseHandle', [wt.HANDLE])
SetDllDirectory = bind('SetDllDirectoryW', [wt.LPCWSTR])


def checked(ok):
    if not ok:
        raise ct.WinError(ct.get_last_error())
    return ok


class OwnedProcess:
    def __init__(self, args, cwd, log_path=None):
        self._lock = threading.RLock()
        self.job = self.handle = None
        self.pid = None
        self.exit_code = None
        info = PROCESSINFO()
        log_file = stdin_file = None
        try:
            self.job = checked(CreateJob(None, None))
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            checked(SetJob(self.job, 9, ct.byref(limits), ct.sizeof(limits)))
            startup = STARTUPINFO()
            startup.cb = ct.sizeof(startup)
            if log_path:
                # Capture native CUDA/llama diagnostics as well as server messages.
                log_file = open(log_path, 'wb', buffering=0)
                stdin_file = open(os.devnull, 'rb')
                output_handle = msvcrt.get_osfhandle(log_file.fileno())
                input_handle = msvcrt.get_osfhandle(stdin_file.fileno())
                os.set_handle_inheritable(output_handle, True)
                os.set_handle_inheritable(input_handle, True)
                startup.dwFlags = 0x100  # STARTF_USESTDHANDLES
                startup.hStdOutput = startup.hStdError = output_handle
                startup.hStdInput = input_handle
            command = ct.create_unicode_buffer(subprocess.list2cmdline(args))
            # PyInstaller's DLL search directory belongs to the GUI, not llama.
            # Restore it immediately after creating the external process.
            frozen = getattr(sys, 'frozen', False)
            if frozen:
                checked(SetDllDirectory(None))
            try:
                checked(CreateProcess(args[0], command, None, None, bool(log_path),
                                      0x08000000 | 0x00000004, None, str(cwd),
                                      ct.byref(startup), ct.byref(info)))
            finally:
                if frozen:
                    checked(SetDllDirectory(str(sys._MEIPASS)))
            self.handle, self.pid = info.hProcess, info.dwProcessId
            checked(AssignJob(self.job, self.handle))
            if ResumeThread(info.hThread) == 0xFFFFFFFF:
                raise ct.WinError(ct.get_last_error())
        except Exception:
            if self.handle:
                Terminate(self.handle, 1)
            self.close()
            raise
        finally:
            if info.hThread:
                Close(info.hThread)
            if log_file:
                log_file.close()
            if stdin_file:
                stdin_file.close()

    def poll(self):
        with self._lock:
            if not self.handle:
                return self.exit_code
            result = Wait(self.handle, 0)
            if result == 0xFFFFFFFF:
                raise ct.WinError(ct.get_last_error())
            if result == 0x102:
                return None
            code = wt.DWORD()
            checked(GetExit(self.handle, ct.byref(code)))
            self.exit_code = code.value
            return self.exit_code

    def close(self):
        with self._lock:
            if self.job:
                checked(Close(self.job))
                self.job = None
            if self.handle:
                if Wait(self.handle, 5000) != 0:
                    checked(Terminate(self.handle, 1))
                    if Wait(self.handle, 5000) != 0:
                        raise RuntimeError('The inference process did not exit.')
                code = wt.DWORD()
                checked(GetExit(self.handle, ct.byref(code)))
                self.exit_code = code.value
                checked(Close(self.handle))
                self.handle = None

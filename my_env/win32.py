#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import os.path
import logging
import functools
import time

import ctypes
import ctypes.wintypes
import ctypes.util

import _winreg as winreg
import msvcrt

logger = logging.getLogger(__name__)

# module global state
class state:
    is_frozen = False
    prevent_screensaver = False

# public interface
def init(is_frozen):
    state.is_frozen = is_frozen

def get_winreg_name(appname):
    return "".join(i for i in appname.encode("ascii", "ignore") if i.isalnum())

class UnsupportedOSException(Exception):
    pass

class OSVERSIONINFOEXW(ctypes.Structure):
    _fields_ = (
        ("dwOSVersionInfoSize", ctypes.wintypes.DWORD),
        ("dwMajorVersion", ctypes.wintypes.DWORD),
        ("dwMinorVersion", ctypes.wintypes.DWORD),
        ("dwBuildNumber", ctypes.wintypes.DWORD),
        ("dwPlatformId", ctypes.wintypes.DWORD),
        ("szCSDVersion", ctypes.c_wchar*128),
        ("wServicePackMajor", ctypes.wintypes.WORD),
        ("wServicePackMinor", ctypes.wintypes.WORD),
        ("wSuiteMask", ctypes.wintypes.WORD),
        ("wProductType", ctypes.wintypes.BYTE),
        ("wReserved", ctypes.wintypes.BYTE)
        )

    def __init__(self):
        self.dwOSVersionInfoSize = ctypes.sizeof(self)

WINVERINFO = OSVERSIONINFOEXW()
ctypes.windll.kernel32.GetVersionExW(ctypes.byref(WINVERINFO))

def get_user_home():
    pbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(0, 40, 0, 0, pbuffer)
    return pbuffer.value

def get_appdata():
    pbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(0, 28, 0, 0, pbuffer)
    return pbuffer.value

def get_my_documents():
    pbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(0, 5, 0, 0, pbuffer)
    return pbuffer.value


SetThreadExecutionState = ctypes.windll.kernel32.SetThreadExecutionState
SetThreadExecutionState.argtypes = (ctypes.c_long,)
SetThreadExecutionState.restype = ctypes.c_long

ES_AWAYMODE_REQUIRED = 0x00000040 if WINVERINFO.dwMajorVersion > 5 else 0 # WinVista+
ES_CONTINUOUS = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002
ES_SYSTEM_REQUIRED = 0x00000001
ES_USER_PRESENT = 0x00000004 if WINVERINFO.dwMajorVersion < 6 else 0 # WinXP and 2003

def set_sleep_mode(active):
    "Sets or unsets System Required (and Away Mode if available) to modify sleep setting"
    # See http://msdn.microsoft.com/en-us/library/aa373208(VS.85).aspx
    r = SetThreadExecutionState(ES_CONTINUOUS if active else ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
    return r != 0  # that is, True if it worked, False if there was an error

def set_screensaver_mode(active):
    state.prevent_screensaver = not active

MOUSEEVENTF_MOVE = 0x0001 # mouse move
MOUSEEVENTF_ABSOLUTE = 0x8000 # absolute move
MOUSEEVENTF_MOVEABS = MOUSEEVENTF_MOVE + MOUSEEVENTF_ABSOLUTE
def idleness_tick():
    if state.prevent_screensaver:
        "Inform the system that it is in use, preventing the screensaver to start"
        # See http://msdn.microsoft.com/en-us/library/aa373208(VS.85).aspx
        r = ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVEABS, 0, 0, 0, 0)

class WIN32_FIND_DATA(ctypes.Structure):
    _fields_ = (
        ("dwFileAttributes", ctypes.wintypes.DWORD),
        ("ftCreationTime", ctypes.wintypes.FILETIME),
        ("ftLastAccessTime", ctypes.wintypes.FILETIME),
        ("ftLastWriteTime", ctypes.wintypes.FILETIME),
        ("nFileSizeHigh", ctypes.wintypes.DWORD),
        ("nFileSizeLow", ctypes.wintypes.DWORD),
        ("dwReserved0", ctypes.wintypes.DWORD),
        ("dwReserved1", ctypes.wintypes.DWORD),
        ("cFileName", ctypes.c_wchar*ctypes.wintypes.MAX_PATH),
        ("cAlternateFileName", ctypes.c_wchar*14),
        )

FindFirstFile = ctypes.windll.kernel32.FindFirstFileW
FindFirstFile.argtypes = (
    ctypes.c_wchar_p,
    ctypes.POINTER(WIN32_FIND_DATA),
    )
FindFirstFile.restype = ctypes.wintypes.HANDLE
FindNextFile = ctypes.windll.kernel32.FindNextFileW
FindNextFile.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(WIN32_FIND_DATA),
    )
FindNextFile.restype = ctypes.c_bool
FindClose = ctypes.windll.kernel32.FindClose
FindClose.argtypes = (
    ctypes.wintypes.HANDLE,
    )
FindClose.restype = ctypes.c_bool
def listdir(path):
    fdFile = WIN32_FIND_DATA()
    sPath = "%s\\*.*" % path

    hFind = FindFirstFile(sPath, ctypes.byref(fdFile))
    if hFind == INVALID_HANDLE_VALUE:
        return None

    r = []
    found = True
    while found:
        r.append(fdFile.cFileName)
        found = FindNextFile(hFind, ctypes.byref(fdFile))
    FindClose(hFind)

    # Blacklisted results
    for i in (".", ".."):
        if i in r:
            r.remove(i)
    return r

def get_downloads():
    pass


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = (
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar*ctypes.wintypes.MAX_PATH)
        )
    def __init__(self):
        self.dwSize = ctypes.sizeof(self)

CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = (
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD
    )
CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE

Process32First = ctypes.windll.kernel32.Process32FirstW
Process32First.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W)
    )
Process32First.restype = ctypes.c_bool

Process32Next = ctypes.windll.kernel32.Process32NextW
Process32Next.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W)
    )
Process32Next.restype = ctypes.c_bool

OpenProcess = ctypes.windll.kernel32.OpenProcess
OpenProcess.argtypes = (
    ctypes.wintypes.DWORD,
    ctypes.c_bool,
    ctypes.wintypes.DWORD
    )
OpenProcess.restype =  ctypes.wintypes.HANDLE

if WINVERINFO.dwMajorVersion > 5:
    # WinVista+
    # Recommended way as said in Remarks section at
    # http://msdn.microsoft.com/en-us/library/windows/desktop/ms683198(v=vs.85).aspx
    QueryFullProcessImageName = ctypes.windll.kernel32.QueryFullProcessImageNameW
    QueryFullProcessImageName.argtypes = (
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.wintypes.DWORD)
        )
    QueryFullProcessImageName.restype = ctypes.c_bool
    def proc_path_by_handle(handle):
        pbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        pbuffsize = ctypes.c_ulong(ctypes.wintypes.MAX_PATH-1)
        success = QueryFullProcessImageName(handle, 0, ctypes.byref(pbuffer), ctypes.byref(pbuffsize))
        if success and pbuffsize > 1:
            return pbuffer.value
        return None
else:
    # WinXP
    GetModuleFileNameEx = ctypes.windll.psapi.GetModuleFileNameExW
    GetModuleFileNameEx.argtypes = (
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.HANDLE,
        ctypes.c_wchar_p,
        ctypes.c_ulong
        )
    GetModuleFileNameEx.restype = ctypes.c_ulong
    def proc_path_by_handle(handle):
        pbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        pbuffsize = GetModuleFileNameEx(handle, 0, ctypes.byref(pbuffer), ctypes.wintypes.MAX_PATH-1)
        if pbuffsize > 1:
            return pbuffer.value
        return None

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
def pids_by_path(path):
    name = os.path.basename(path)
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W()
    success = Process32First(snapshot, ctypes.byref(entry))
    while success:
        # First check: name
        if entry.szExeFile == name:
            handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, entry.th32ProcessID)
            # Second check: availability
            if handle:
                fullname = proc_path_by_handle(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
                # Third check: full path
                if fullname == path:
                    yield entry.th32ProcessID
        success = Process32Next(snapshot, ctypes.byref(entry))

GetDiskFreeSpaceEx = ctypes.windll.kernel32.GetDiskFreeSpaceExW
GetDiskFreeSpaceEx.argtypes = (
    ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.wintypes.ULARGE_INTEGER),
    ctypes.POINTER(ctypes.wintypes.ULARGE_INTEGER),
    ctypes.POINTER(ctypes.wintypes.ULARGE_INTEGER)
    )
def get_free_space(path):
    free_bytes = ctypes.wintypes.ULARGE_INTEGER(0)
    GetDiskFreeSpaceEx(path, None, None, ctypes.byref(free_bytes))
    return free_bytes.value

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102
INFINITE =  0xFFFFFFFF
def get_running(pid, path=None, max_ctime=None):
    '''
    Get if given pid is running.

    On windows, due its high pid recycling rate, pid could being
    used by any unwanted process, so two extra kwargs are given for
    workaround this issue.

    Args:
        pid: int, process identifier.
        path: unicode or None, optional executable path.
        max_ctime: float or None, optional max accepted value for
                   process creation time.

    Returns:
        True if any process satisfy given criteria, False otherwise.

    '''
    flags = SYNCHRONIZE
    if path:
        # PROCESS_QUERY_INFORMATION is valid for max_ctime too
        flags |= PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    elif max_ctime:
        if WINVERINFO.dwMajorVersion > 5: # WinVista+
            flags |= PROCESS_QUERY_LIMITED_INFORMATION
        else:
            flags |= PROCESS_QUERY_INFORMATION
    handle = ctypes.windll.kernel32.OpenProcess(flags, 0, pid)
    if handle:
        try:
            if path:
                cpath = proc_path_by_handle(handle)
                logger.debug("get_running: %s == %s" % (cpath, path))
                if cpath and not samefile(cpath, path):
                    return False
            if max_ctime:
                ctime = proc_ctime_by_handle(handle)
                logger.debug("get_running: %f >= %f" % (ctime, max_ctime))
                if ctime and ctime >= max_ctime:
                    return False
            timeout = ctypes.wintypes.DWORD(0)
            r = ctypes.windll.kernel32.WaitForSingleObject(handle, timeout)
            return r == WAIT_TIMEOUT
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    return False

def wait_pid(pid):
    '''
    Waits for process with pid is finished.
    '''
    flags = SYNCHRONIZE
    handle = ctypes.windll.kernel32.OpenProcess(flags, 0, pid)
    if handle:
        try:
            # Detect if running
            timeout = ctypes.wintypes.DWORD(0)
            r = ctypes.windll.kernel32.WaitForSingleObject(handle, timeout)

            # Wait for completion
            if r == WAIT_TIMEOUT:
                ctypes.windll.kernel32.WaitForSingleObject(handle, INFINITE)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

class SYSTEMTIME(ctypes.Structure):
    _fields_ = (
        ("wYear", ctypes.wintypes.WORD),
        ("wMonth", ctypes.wintypes.WORD),
        ("wDayOfWeek", ctypes.wintypes.WORD),
        ("wDay", ctypes.wintypes.WORD),
        ("wHour", ctypes.wintypes.WORD),
        ("wMinute", ctypes.wintypes.WORD),
        ("wSecond", ctypes.wintypes.WORD),
        ("wMilliseconds", ctypes.wintypes.WORD),
        )

    def as_epoch(self):
        return time.mktime((
            self.wYear, self.wMonth, self.wDay,
            self.wHour, self.wMinute, min(self.wSecond, 59),
            6 if self.wDayOfWeek == 0 else (self.wDayOfWeek - 1),
            -1, 0
            ))

class FILETIME(ctypes.Structure):
    _fields_ = (
        ("low", ctypes.c_ulong),
        ("high", ctypes.c_ulong),
        )

    def as_epoch(self):
        systemTime = SYSTEMTIME()
        success = ctypes.windll.kernel32.FileTimeToSystemTime(
            ctypes.pointer(self),
            ctypes.byref(systemTime)
            )
        if success:
            return systemTime.as_epoch() + self.low / 1e7
        raise WindowsError, "Cannot convert FILETIME to SYSTEMTIME."


def proc_ctime_by_handle(handle):
    creationtime = FILETIME(0, 0)
    trash = ctypes.byref(FILETIME(0, 0))
    success = ctypes.windll.kernel32.GetProcessTimes(
        handle, ctypes.byref(creationtime), trash, trash, trash
        )
    if success:
        return creationtime.as_epoch()
    return None

GetCommandLine = ctypes.cdll.kernel32.GetCommandLineW
GetCommandLine.argtypes = ()
GetCommandLine.restype = ctypes.wintypes.LPCWSTR
CommandLineToArgv = ctypes.windll.shell32.CommandLineToArgvW
CommandLineToArgv.argtypes = (
    ctypes.wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_int)
    )
CommandLineToArgv.restype = ctypes.POINTER(ctypes.wintypes.LPWSTR)
def get_argv():
    '''
    Uses shell32.GetCommandLineArgvW to get sys.argv as a list of unicode
    strings.

    Versions 2.5 and older of Python don't support Unicode in sys.argv on
    Windows, with the underlying Windows API instead replacing multi-byte
    characters with '?'.

    Returns empty list on failure.

    Example usage:

    >>> def main(argv=None):
    ...    if argv is None:
    ...        argv = get_argv() or sys.argv
    ...
    '''

    try:
        cmd = GetCommandLine()
        argc = ctypes.c_int(0)
        argv = CommandLineToArgv(cmd, ctypes.byref(argc))
        if argc.value > 0:
            # Remove Python executable if present
            if argc.value - len(sys.argv) == 1:
                start = 1
            else:
                start = 0
            return [argv[i] for i in xrange(start, argc.value)]
    except BaseException as e:
        logger.exception(e)
    return []

def signal_callback(callback, signum):
    r = callback(signum, None)
    try:
        return int(r)
    except:
        return 1

def set_signal_handler(handler):
    fnctype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
    handler = fnctype(functools.partial(signal_callback, handler))

    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, 1)

    '''
    for sig in (signal.SIGABRT, signal.SIGFPE, signal.SIGILL,
                signal.SIGINT, signal.SIGSEGV, signal.SIGTERM):
        signal.signal(sig, handler)
    '''

FILE_READ_ATTRIBUTES = 0x80
FILE_READ_EA = 8
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
def get_file_handle(path):
    return ctypes.windll.kernel32.CreateFileW(
        path if isinstance(path, unicode) else path.decode("utf-8"),
        FILE_READ_ATTRIBUTES | FILE_READ_EA,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, 0, None)

def get_file_time(path):
    '''
    Some filesystems
    '''
    ctime = FILETIME(0, 0)
    atime = FILETIME(0, 0)
    mtime = FILETIME(0, 0)

    handle = get_file_handle(path)

    if handle:
        try:
            ctypes.windll.kernel32.GetFileTime(
                handle,
                ctypes.byref(ctime),
                ctypes.byref(atime),
                ctypes.byref(mtime)
                )
            return (ctime.as_epoch(), atime.as_epoch(), mtime.as_epoch())
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    return (0, 0, 0)

class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("dwFileAttributes", ctypes.wintypes.DWORD),
        ("ftCreationTime", FILETIME),
        ("ftLastAccessTime", FILETIME),
        ("ftLastWriteTime", FILETIME),
        ("dwVolumeSerialNumber", ctypes.wintypes.DWORD),
        ("nFileSizeHigh", ctypes.wintypes.DWORD),
        ("nFileSizeLow", ctypes.wintypes.DWORD),
        ("nNumberOfLinks", ctypes.wintypes.DWORD),
        ("nFileIndexHigh", ctypes.wintypes.DWORD),
        ("nFileIndexLow", ctypes.wintypes.DWORD)
        )

GetFileInformationByHandle = ctypes.windll.kernel32.GetFileInformationByHandle
GetFileInformationByHandle.argtypes = (
    ctypes.wintypes.HANDLE, # _In_   HANDLE hFile,
    ctypes.POINTER(BY_HANDLE_FILE_INFORMATION) # _Out_  LPBY_HANDLE_FILE_INFORMATION lpFileInformation
    )
GetFileInformationByHandle.restype = ctypes.c_bool
def get_fileindex(path):
    handle = get_file_handle(path)
    fileinfo = BY_HANDLE_FILE_INFORMATION()
    GetFileInformationByHandle(handle, ctypes.byref(fileinfo))
    indexhi = fileinfo.nFileIndexHigh
    indexlo = fileinfo.nFileIndexLow
    ctypes.windll.kernel32.CloseHandle(handle)
    return (indexhi, indexlo)

def samefile(path1, path2):
    return path1 == path2 or get_fileindex(path1) == get_fileindex(path2)

class SHELLEXECUTEINFO(ctypes.Structure):
    '''
    Helper class for windll ShellExecuteEx
    '''
    _fields_ = (
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.wintypes.HANDLE),
        ("lpVerb", ctypes.c_char_p),
        ("lpFile", ctypes.c_char_p),
        ("lpParameters", ctypes.c_char_p),
        ("lpDirectory", ctypes.c_char_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_char_p),
        ("hKeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
        )

class STARTUPINFO(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.wintypes.LPWSTR),
        ("lpDesktop", ctypes.wintypes.LPWSTR),
        ("lpTitle", ctypes.wintypes.LPWSTR),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.wintypes.BYTE)),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
        )

    def __init__(self):
        ctypes.Structure.__init__(self)
        self.cb = ctypes.sizeof(self)
        self.lpReserved = None

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessID", ctypes.wintypes.DWORD),
        ("dwThreadID", ctypes.wintypes.DWORD),
        )

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = (
        ("nLength", ctypes.wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.wintypes.BOOL),
        )

    def __init__(self):
        ctypes.Structure.__init__(self)
        self.lpSecurityDescriptor = None
        self.nLength = ctypes.sizeof(self)

# PID of handle
if WINVERINFO.dwMajorVersion > 5 or ( # WinVista+
  WINVERINFO.dwMajorVersion == 5 and # Win2000/XP
  WINVERINFO.dwMinorVersion > 0 and # WinXP
  WINVERINFO.wServicePackMajor > 0 # SP1+
  ):
    get_pid_from_handle = ctypes.windll.kernel32.GetProcessId
else:
    # TODO(felipe): very low priority - implement for WinNT versions prior to XP SP1
    # http://msdn.microsoft.com/en-us/library/windows/desktop/ms687420(v=vs.85).aspx
    # http://www.codeproject.com/Articles/21926/Getting-Process-ID-from-Process-Handle
    '''
    ntdll = ctypes.CDLL("Ntdll.dll")
    def get_pid_from_handle(pid):
        processHandle =
        processInfoClass =
        processInformation = ctypes.ulong()
        processInformationLength = ctypes.ulong()
        returnLength = ctypes.ulong()
    '''
    raise UnsupportedOSException("This program requires at least WinXP SP1.")

max_half_open = None
if WINVERINFO.dwMajorVersion < 6: # WinXP
    max_half_open = 8 # WinXP: 10
elif WINVERINFO.dwMajorVersion == 6 and WINVERINFO.dwMinorVersion == 0 and WINVERINFO.wServicePackMajor < 2: # Vista SP2-
    max_half_open = 4 # WinVista limit prior SP2: 5

def get_max_half_open_connections():
    return max_half_open

S_OK = 0
def composite():
    if WINVERINFO.dwMajorVersion > 5: # WinVista+
        b = ctypes.c_bool()
        r = ctypes.windll.dwmapi.DwmIsCompositionEnabled(ctypes.byref(b))
        return r == S_OK and b.value
    return False

class MARGINS(ctypes.Structure):
    _fields_ = (
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int)
        )

DWM_BB_ENABLE = 0x00000001 # A value for the fEnable member has been specified.
DWM_BB_BLURREGION = 0x00000002 # A value for the hRgnBlur member has been specified.
DWM_BB_TRANSITIONONMAXIMIZED = 0x00000004 # A value for the fTransitionOnMaximized member has been specified.
class DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = (
        ("dwFlags", ctypes.wintypes.DWORD),
        ("fEnable", ctypes.c_bool),
        ("hRgnBlur", ctypes.wintypes.HANDLE),
        ("fTransitionOnMaximized", ctypes.c_bool),
        )

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_COMPOSITED = 0x02000000L
def window_long(wxframe, add=0, remove=0):
    handle = wxframe.GetHandle()
    window_long = ctypes.windll.user32.GetWindowLongW(handle, GWL_EXSTYLE)
    if add or remove:
        window_long |= add
        window_long ^= remove
        ctypes.windll.user32.SetWindowLongW(
            handle, ctypes.c_int(GWL_EXSTYLE), ctypes.c_long(window_long))
    return window_long

def RGBA(r, g, b, a=255):
    return (a & 0xFF) << 24 | (r & 0xFF) << 16 | (g & 0xFF) << 8 | b & 0xFF

LWA_ALPHA = 0x00000002 # Use bAlpha to determine the opacity of the layered window
LWA_COLORKEY = 0x00000001 # Use crKey as the transparency color
def composite_frame(wxframe, margins=-1, blur=None, transparent_color=None):
    '''
    Margins is a tuple with margin values in clockwise order
    '''
    if hasattr(wxframe.__class__, "unproxize"):
        wxframe = wxframe.__class__.unproxize(wxframe)
    '''
    if transparent_color is None:
        pcrColorization = ctypes.wintypes.DWORD(0)
        pfOpaqueBlend = ctypes.c_bool(False)
        error = ctypes.windll.dwmapi.DwmGetColorizationColor(
            ctypes.byref(pcrColorization),
            ctypes.byref(pfOpaqueBlend)
            )
        if error:
            transparent_color = (255, 0, 255, 0) # Magic pink
        else:
            l = pcrColorization.value
            rgb = int((l & 0xFF0000) >> 16), int((l & 0xFF00) >> 8), int(l & 0xFF)
            mid = (rgb[0]+rgb[2])/2
            transparent_color = mid, rgb[1], mid, 0

            if max(rgb) < 128:
                transparent_color = [i+32 for i in transparent_color]

    elif len(transparent_color) < 4:
        transparent_color = transparent_color[0], transparent_color[1], transparent_color[2], 0

    if isinstance(margins, (int, long)):
        margins = (margins,)*4
    elif len(margins) == 1:
        margins = tuple(margins)*4
    elif len(margins) == 2:
        margins = tuple(margins)*2
    elif len(margins) == 3:
        margins = (margins[0], margins[1], margins[2], margins[1])
    '''
    handle = wxframe.GetHandle()

    '''
    # Defining color key
    window_long(wxframe, WS_EX_LAYERED)
    r = ctypes.windll.user32.SetLayeredWindowAttributes(
        handle, RGBA(*transparent_color), 0, LWA_COLORKEY)
    wxframe.SetBackgroundColour(wx.Colour(*transparent_color))
    '''

    # Resizing margins
    margins = ctypes.byref(MARGINS(margins[3], margins[1], margins[0], margins[2]))
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(handle, margins)

    # Setting blur
    if not blur is None:
        behind = ctypes.byref(DWM_BLURBEHIND(DWM_BB_ENABLE, blur))
        ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(handle, behind)

    wxframe.Refresh()

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_INVOKEIDLIST = 0x0000000C
SEE_MASK_WAITFORINPUTIDLE  = 0x02000000
SEE_MASK_UNICODE = 0x00004000
SEE_MASK_NO_CONSOLE = 0x00008000

NORMAL_PRIORITY_CLASS = 0x00000020
SW_HIDE = 0

STARTF_USESHOWWINDOW = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
CREATE_NO_WINDOW = 0x08000000

STD_INPUT_HANDLE = ctypes.wintypes.DWORD(-10)
STD_OUTPUT_HANDLE = ctypes.wintypes.DWORD(-11)
STD_ERROR_HANDLE = ctypes.wintypes.DWORD(-12)

def quote_param(param):
    if " " in param:
        if param[0] in "-/":
            return param # We do not take care of arguments
        elif param[0] != param[1] or param[0] in "\"'":
            return "\"%s\"" % param.replace("\"","\\\"")
    return param

def short_pathname(path):
    shortpath = ctypes.create_string_buffer(512)
    success = ctypes.windll.kernel32.GetShortPathName(path, shortpath, ctypes.sizeof(shortpath))
    if success:
        return shortpath.value
    return path


def call(cmd, shell=False, shellexec=False, verb="open", show=True, unicode_env=True):
    '''
    Run command using windows API, and return pid (or 0 on error)
    '''
    assert isinstance(cmd, (tuple, list)), "Use tuples for commands"

    # Running in shell has some problems
    if shell:
        # Problematic pathnames
        if cmd[0].count("?") != cmd[0].encode("ascii", "replace").count("?"):
            executable = short_pathname(cmd[0])
        else:
            executable = quote_param(cmd[0])
        params = " ".join(quote_param(param) for param in cmd[1:])
        cmdline = executable + " " + params
    else:
        # No shell, we can use unicode pathnames
        executable = cmd[0]
        params = " ".join(quote_param(param) for param in cmd[1:])
        cmdline = quote_param(executable) + " " + params

    if shellexec:
        creationflags = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_INVOKEIDLIST | SEE_MASK_WAITFORINPUTIDLE
        if not shell:
            creationflags |= SEE_MASK_NO_CONSOLE

        if unicode_env:
            creationflags |= SEE_MASK_UNICODE

        sei = SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(sei)
        sei.fMask = creationflags
        sei.lpVerb = verb
        sei.lpFile = executable
        sei.lpParameters = params
        sei.nShow = int(show)
        ctypes.windll.shell32.ShellExecuteEx(ctypes.byref(sei))
        if sei.hProcess:
            pid = get_pid_from_handle(sei.hProcess)
            ctypes.windll.kernel32.CloseHandle(sei.hProcess)
            logger.debug("ShellExec %s (pid %d)" % (cmd[0], pid))
            return pid
    else:
        sinfo = STARTUPINFO()
        pinfo = PROCESS_INFORMATION()
        cflags = NORMAL_PRIORITY_CLASS

        if not show:
            sinfo.dwFlags |= STARTF_USESHOWWINDOW
            sinfo.wShowWindow |= SW_HIDE
            cflags |= CREATE_NO_WINDOW

        # stdin, stdout, stderr redirection
        stdin = ctypes.windll.kernel32.GetStdHandle(STD_INPUT_HANDLE)

        if hasattr(sys.stdout, "fileno"):
            stdout = msvcrt.get_osfhandle(sys.stdout.fileno())
        else:
            stdout = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

        if hasattr(sys.stderr, "fileno"):
            stderr = msvcrt.get_osfhandle(sys.stderr.fileno())
        else:
            stderr = ctypes.windll.kernel32.GetStdHandle(STD_ERROR_HANDLE)

        sinfo.dwFlags |= STARTF_USESTDHANDLES
        sinfo.hStdInput = stdin
        sinfo.hStdOutput = stdout
        sinfo.hStdError = stderr

        #sec = SECURITY_ATTRIBUTES()
        #sec.bInheritHandle = True
        ctypes.windll.kernel32.CreateProcessW(
            None if shell else ctypes.wintypes.LPCWSTR(executable), # lpApplicationName
            ctypes.wintypes.LPWSTR(cmdline), # lpCommandLine
            None, #ctypes.byref(sec), # lpProcessAttributes
            None, #ctypes.byref(sec), # lpThreadAttributes
            ctypes.wintypes.BOOL(True), # bInheritHandles
            ctypes.wintypes.DWORD(cflags), # dwCreationFlags
            ctypes.c_void_p(), # lpEnvironment
            ctypes.c_void_p(), # lpCurrentDirectory
            ctypes.byref(sinfo), # lpStartupInfo
            ctypes.byref(pinfo) # lpProcessInformation
            )
        if pinfo.hProcess:
            pid = get_pid_from_handle(pinfo.hProcess)
            ctypes.windll.kernel32.CloseHandle(pinfo.hProcess)
            ctypes.windll.kernel32.CloseHandle(pinfo.hThread)
            logger.debug("CreateProcess %s (pid %d)" % (executable, pid))
            return pid
    return 0  # if we got here, there was an error somewhere


PROCESS_TERMINATE = 0x0001
def kill(pid):
    process = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, 0, pid)
    if process:
        ctypes.windll.kernel32.TerminateProcess(process, 0)
        ctypes.windll.kernel32.CloseHandle(process)

def killall(path):
    for pid in pids_by_path(path):
        kill(pid)

def register_get_exe_path(winreg_name):
    HKCR = winreg.HKEY_CLASSES_ROOT
    try:
        return winreg.QueryValue(HKCR, "%s\shell\open\command" % winreg_name).split("\" \"", 1)[0][1:]
    except:
        pass
    return os.path.abspath(sys.executable) if state.is_frozen else None

def register(appname):
    '''
    Register Download Manager on windows register
    '''
    HKCR = winreg.HKEY_CLASSES_ROOT
    HKCU = winreg.HKEY_CURRENT_USER
    string = winreg.REG_SZ

    # TODO(felipe): ed2k register keys

    winreg_name = get_winreg_name(appname)
    exe_path = register_get_exe_path(winreg_name)
    if exe_path is None:
        return

    for root, prefix in (
        (HKCR, "Magnet"),
        (HKCU, "Software\Classes\Magnet")
        ):
        try:
            winreg.SetValue(root, "%s" % prefix, string, "Magnet URI")
            winreg.SetValue(root, "%s\Content Type" % prefix, string, "application/x-magnet")
            winreg.CreateKey(root, "%s\URL Protocol" % prefix)
            winreg.SetValue(root, "%s\DefaultIcon" % prefix, string, "\"%s\",0" % exe_path)
            winreg.SetValue(root, "%s\shell" % prefix, string, "")
            winreg.SetValue(root, "%s\shell\open" % prefix, string, "open")
            winreg.SetValue(root, "%s\shell\open\command" % prefix, string, "\"%s\" \"%%1\"" % exe_path)
        except WindowsError:
            roots = [k for k, v in locals().iteritems() if v == root and k.startswith("HKEY")]
            logger.warn("Cannot set registry key in %s\%s." % (roots[0] if roots else root, prefix))

    for root, prefix in (
        (HKCR, ".torrent"),
        (HKCU, "Software\Classes\.torrent")
        ):
        try:
            winreg.SetValue(root, "%s" % prefix, string, winreg_name)
            winreg.SetValue(root, "%s\Content Type" % prefix, string, "application/x-bittorrent")
            winreg.SetValue(root, "%s\OpenWithProgids" % prefix, string, winreg_name)
        except WindowsError:
            roots = [k for k, v in locals().iteritems() if v == root and k.startswith("HKEY")]
            logger.warn("Cannot set registry key in %s\%s." % (roots[0] if roots else root, prefix))

def get_register(appname):
    HKCU = winreg.HKEY_CURRENT_USER
    winreg_name = get_winreg_name(appname)
    exe_path = register_get_exe_path(winreg_name)
    key = "Software\Classes\Magnet\shell\open\command"
    if exe_path is None:
        return False
    try:
        expected = "\"%s\" \"%%1\"" % exe_path
        if winreg.QueryValue(HKCU, key) != expected:
            return False
        key = "Software\Classes\.torrent\OpenWithProgids"
        if winreg.QueryValue(HKCU, key) != winreg_name:
            return False
    except WindowsError:
        return False
    return True

class COM:
    E_ACCESSDENIED = 0x80070005 # Access denied.
    E_FAIL = 0x80004005 # Unspecified error.
    E_INVALIDARG = 0x80070057 # Invalid parameter value.
    E_OUTOFMEMORY = 0x8007000E # Out of memory.
    E_POINTER = 0x80004003 # NULL was passed incorrectly for a pointer value.
    E_UNEXPECTED = 0x8000FFFF # Unexpected condition.
    S_OK = 0x0 # Success.
    S_FALSE = 0x1 # Success.

class ASSOCF:
    NONE                  = 0x00000000
    INIT_NOREMAPCLSID     = 0x00000001
    INIT_BYEXENAME        = 0x00000002
    OPEN_BYEXENAME        = 0x00000002
    INIT_DEFAULTTOSTAR    = 0x00000004
    INIT_DEFAULTTOFOLDER  = 0x00000008
    NOUSERSETTINGS        = 0x00000010
    NOTRUNCATE            = 0x00000020
    VERIFY                = 0x00000040
    REMAPRUNDLL           = 0x00000080
    NOFIXUPS              = 0x00000100
    IGNOREBASECLASS       = 0x00000200
    INIT_IGNOREUNKNOWN    = 0x00000400
    INIT_FIXED_PROGID     = 0x00000800
    IS_PROTOCOL           = 0x00001000

class ASSOCSTR:
    COMMAND = 1
    EXECUTABLE = 2
    FRIENDLYDOCNAME = 3
    FRIENDLYAPPNAME = 4
    NOOPEN = 5
    SHELLNEWVALUE = 6
    DDECOMMAND = 7
    DDEIFEXEC = 8
    DDEAPPLICATION = 9
    DDETOPIC = 10
    INFOTIP = 11
    QUICKTIP = 12
    TILEINFO = 13
    CONTENTTYPE = 14
    DEFAULTICON = 15
    SHELLEXTENSION = 16
    DROPTARGET = 17
    DELEGATEEXECUTE = 18
    SUPPORTED_URI_PROTOCOLS = 19
    MAX = 20

AssocQueryString = ctypes.windll.Shlwapi.AssocQueryStringW
AssocQueryString.argtypes = (
    ctypes.c_int, ctypes.c_int,
    ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.wintypes.DWORD))
AssocQueryString.restype = ctypes.wintypes.HRESULT

FindExecutable = ctypes.windll.shell32.FindExecutableW
FindExecutable.argtypes = (
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p
    )
FindExecutable.restype = ctypes.wintypes.HINSTANCE

class SE_ERR:
    FNF = 2 # The specified file was not found.
    PNF = 3 # The specified path is invalid.
    ACCESSDENIED = 5 # The specified file cannot be accessed.
    OOM = 8 # The system is out of memory or resources.
    NOASSOC = 31 # There is no association for the specified file type with an executable file.

def file_association(path):
    if not "." in os.path.basename(path):
        return None

    rbuffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH-1)
    h = FindExecutable(ctypes.create_unicode_buffer(path), None, rbuffer)

    if h < 33:
        # 32 or less means error
        return None

    path = rbuffer.value

    # Given exe is absolute path
    #if os.path.isabs(path):
    #    return path

    # If not, we must get the real path
    rsize = ctypes.wintypes.DWORD(ctypes.wintypes.MAX_PATH-1)
    rbuffer = ctypes.create_unicode_buffer(rsize.value)

    r = AssocQueryString(
        ASSOCF.OPEN_BYEXENAME, ASSOCSTR.EXECUTABLE,
        ctypes.create_unicode_buffer(path), None, rbuffer, ctypes.byref(rsize))

    # We should test r against COM.S_FALSE and COM.E_POINTER, but we're
    # using MAX_PATH size for buffering a path so there is no need to do so
    return rbuffer.value

GetFileAttributes = ctypes.windll.kernel32.GetFileAttributesW
GetFileAttributes.argtypes = (ctypes.c_wchar_p, )
GetFileAttributes.restype = ctypes.wintypes.DWORD
def file_hidden(path):
    attrs = GetFileAttributes(path)
    return attrs != -1 and attrs & 2

def startup(appname):
    winreg_name = get_winreg_name(appname)
    HKCU = winreg.HKEY_CURRENT_USER
    KEY_WRITE = winreg.KEY_WRITE
    REG_SZ = winreg.REG_SZ
    exe_path = register_get_exe_path(winreg_name)
    key = "Software\Microsoft\Windows\CurrentVersion\Run"
    if exe_path is None:
        return
    try:
        try:
            keyobj = winreg.OpenKey(HKCU, key, 0, KEY_WRITE)
        except:
            keyobj = winreg.CreateKey(HKCU, key)
        winreg.SetValueEx(keyobj, winreg_name, 0, REG_SZ, "\"%s\" --startup" % exe_path)
        winreg.CloseKey(keyobj)
    except WindowsError:
        logger.warn("Cannot set registry key in HKCU\%s\%s." % (key, winreg_name))

def startup_disable(appname):
    winreg_name = get_winreg_name(appname)
    HKCU = winreg.HKEY_CURRENT_USER
    KEY_WRITE = winreg.KEY_WRITE
    key = "Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        keyobj = winreg.OpenKey(HKCU, key, 0, KEY_WRITE)
        try:
            winreg.DeleteValue(keyobj, winreg_name)
        except:
            pass
        winreg.CloseKey(keyobj)
    except WindowsError:
        logger.warn("Cannot remove registry key in HKCU\%s\%s." % (key, winreg_name))

def get_startup(appname):
    winreg_name = get_winreg_name(appname)
    HKCU = winreg.HKEY_CURRENT_USER
    KEY_QUERY_VALUE = winreg.KEY_QUERY_VALUE
    exe_path = register_get_exe_path(winreg_name)
    key = "Software\Microsoft\Windows\CurrentVersion\Run"
    if exe_path is None:
        return False
    try:
        keyobj = winreg.OpenKey(HKCU, key, 0, KEY_QUERY_VALUE)
        try:
            rvalue, rtype = winreg.QueryValueEx(keyobj, winreg_name)
        except:
            rvalue, rtype = None, None
        winreg.CloseKey(keyobj)
        return rvalue == "\"%s\" --startup" % exe_path
    except WindowsError:
        logger.debug("Cannot get registry key in HKCU\%s\%s." % (key, winreg_name))
    return False

def get_ieversion():
    HKCL = winreg.HKEY_LOCAL_MACHINE
    KEY_QUERY_VALUE = winreg.KEY_QUERY_VALUE
    key = "Software\Microsoft\Internet Explorer"
    keystring = "Version"
    try:
        keyobj = winreg.OpenKey(HKCL, key, 0, KEY_QUERY_VALUE)
        rvalue, rtype = winreg.QueryValueEx(keyobj, keystring)
        winreg.CloseKey(keyobj)
        return [int(i) if i.isdigit() else i for i in rvalue.split(".")]
    except WindowsError:
        logger.debug("Cannot get registry key in HKCL\%s\%s." % (key, keystring))
    return None

def force_ie_edge(appname):
    winreg_name = get_winreg_name(appname)
    exe_path = register_get_exe_path(winreg_name) or sys.executable
    ieversion = get_ieversion()
    HKCU = winreg.HKEY_CURRENT_USER
    KEY_WRITE = winreg.KEY_WRITE
    if 8 < ieversion[0] < 11: # Use FEATURE_BROWSER_EMULATION
        key = "Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION"
        subkey = os.path.basename(exe_path)
        vtype = winreg.REG_DWORD
        if ieversion > 10:
            value = 0x2711
        elif ieversion > 9:
            value = 0x270F
        elif ieversion > 8:
            value = 0x22B8
    else:
        return
    try:
        try:
            keyobj = winreg.OpenKey(HKCU, key, 0, KEY_WRITE)
        except:
            keyobj = winreg.CreateKey(HKCU, key)
        winreg.SetValueEx(keyobj, subkey, 0, vtype, value)
    except WindowsError:
        logger.debug("Cannot set registry key in HKCU\%s\%s." % (key, subkey))

def blocksize(path):
    '''
    Get path's filesystem block size
    '''
    drive, path = os.path.splitdrive(path)

    sectorsPerCluster = ctypes.c_ulonglong(0)
    bytesPerSector = ctypes.c_ulonglong(0)
    rootPathName = ctypes.c_wchar_p(drive)

    ctypes.windll.kernel32.GetDiskFreeSpaceW(
        rootPathName,
        ctypes.byref(sectorsPerCluster),
        ctypes.byref(bytesPerSector),
        None, None)
    return sectorsPerCluster.value * bytesPerSector.value

MB_ICONERROR = 0x00000010L
MB_TASKMODAL = 0x00002000L
TDCBF_OK_BUTTON = 0x0001
TDCBF_CANCEL_BUTTON = 0x0008
TDCBF_CLOSE_BUTTON = 0x0020
TD_ERROR_ICON = 65534
def error_message(title, message):
    if WINVERINFO.dwMajorVersion > 5: # Vista and so on, use TaskDialog
        message, content = message.split("\n\n", 1) if "\n\n" in message else (message, None)
        out = ctypes.c_int32(0)
        ctypes.windll.comctl32.TaskDialog(None, None, title, message, content,
             TDCBF_OK_BUTTON, TD_ERROR_ICON, ctypes.byref(out))
    else:
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR | MB_TASKMODAL)

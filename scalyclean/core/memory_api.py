"""Purge standby / working sets — правильный вызов NtSetSystemInformation + привилегии."""

import ctypes
from ctypes import wintypes

ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

SystemMemoryListInformation = 80
MemoryEmptyWorkingSets = 2
MemoryFlushModifiedList = 3
MemoryPurgeStandbyList = 4
MemoryPurgeLowPriorityStandbyList = 5

NTSTATUS = wintypes.LONG
ntdll.NtSetSystemInformation.argtypes = [
    wintypes.ULONG,
    wintypes.LPVOID,
    wintypes.ULONG,
]
ntdll.NtSetSystemInformation.restype = NTSTATUS

_last_status: int = 0


def last_ntstatus() -> int:
    return _last_status


def ntstatus_name(status: int) -> str:
    if status == 0:
        return "OK"
    if status == 0xC0000022:
        return "ACCESS_DENIED"
    if status == 0xC000000D:
        return "INVALID_PARAMETER"
    return hex(status & 0xFFFFFFFF)


def _enable_privilege(name: str) -> bool:
    TOKEN_ADJUST_PRIVILEGES = 0x0020
    TOKEN_QUERY = 0x0008
    SE_PRIVILEGE_ENABLED = 0x00000002

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    h_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(h_token),
    ):
        return False
    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        kernel32.CloseHandle(h_token)
        return False
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    advapi32.AdjustTokenPrivileges(h_token, False, ctypes.byref(tp), 0, None, None)
    kernel32.CloseHandle(h_token)
    return True


def _rtl_adjust_privilege(privilege_id: int) -> bool:
    try:
        if not hasattr(ntdll, "RtlAdjustPrivilege"):
            return False
        ntdll.RtlAdjustPrivilege.argtypes = [
            wintypes.ULONG,
            wintypes.BYTE,
            wintypes.BYTE,
            ctypes.POINTER(wintypes.BYTE),
        ]
        ntdll.RtlAdjustPrivilege.restype = NTSTATUS
        was = wintypes.BYTE()
        st = ntdll.RtlAdjustPrivilege(privilege_id, 1, 0, ctypes.byref(was))
        return st == 0
    except Exception:
        return False


def _prepare_memory_privileges() -> None:
    for priv in (
        "SeProfileSingleProcessPrivilege",
        "SeIncreaseQuotaPrivilege",
        "SeDebugPrivilege",
    ):
        _enable_privilege(priv)
    # Win10/11: индекс SeProfileSingleProcessPrivilege (если LookupPrivilege не сработал)
    for pid in (13, 7, 11):
        _rtl_adjust_privilege(pid)


def _memory_list_command(cmd: int) -> bool:
    global _last_status
    _prepare_memory_privileges()
    # Важно: в буфер передаётся только ULONG-команда, не структура из 8 байт.
    command = wintypes.ULONG(cmd)
    _last_status = ntdll.NtSetSystemInformation(
        SystemMemoryListInformation,
        ctypes.byref(command),
        ctypes.sizeof(command),
    )
    return _last_status == 0


def purge_standby_lists(low_priority_only: bool = False) -> bool:
    cmd = MemoryPurgeLowPriorityStandbyList if low_priority_only else MemoryPurgeStandbyList
    return _memory_list_command(cmd)


def empty_all_working_sets() -> bool:
    return _memory_list_command(MemoryEmptyWorkingSets)


def flush_modified_list() -> bool:
    return _memory_list_command(MemoryFlushModifiedList)


def flush_system_file_cache() -> bool:
    """Доп. сброс файлового кэша (psapi)."""
    try:
        SIZE_T = ctypes.c_size_t
        psapi.SetSystemFileCacheSize.argtypes = [SIZE_T, SIZE_T, wintypes.DWORD]
        psapi.SetSystemFileCacheSize.restype = wintypes.BOOL
        return bool(psapi.SetSystemFileCacheSize(SIZE_T(-1), SIZE_T(-1), 0))
    except Exception:
        return False


def trim_current_process_ws() -> bool:
    try:
        h = kernel32.GetCurrentProcess()
        return bool(psapi.EmptyWorkingSet(h))
    except Exception:
        return False

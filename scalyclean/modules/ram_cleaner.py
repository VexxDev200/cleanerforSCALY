import ctypes
from dataclasses import dataclass

import psutil

from scalyclean.core.admin import is_admin
from scalyclean.core.gentle_mode import should_skip_ram_trim
from scalyclean.core.memory_api import (
    empty_all_working_sets,
    flush_modified_list,
    flush_system_file_cache,
    last_ntstatus,
    ntstatus_name,
    purge_standby_lists,
)


@dataclass
class RamStats:
    total: int
    available: int
    used: int
    percent: float


@dataclass
class RamCleanReport:
    standby_purged: bool
    working_sets_emptied: bool
    modified_flushed: bool
    processes_trimmed: int
    errors: list[str]
    before: RamStats
    after: RamStats


def get_ram_stats() -> RamStats:
    v = psutil.virtual_memory()
    return RamStats(
        total=v.total,
        available=v.available,
        used=v.used,
        percent=v.percent,
    )


def trim_process_working_sets(skip_names: set[str] | None = None) -> tuple[int, list[str]]:
    skip = skip_names or set()
    count = 0
    errors: list[str] = []
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    OpenProcess = kernel32.OpenProcess
    OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    OpenProcess.restype = ctypes.c_void_p

    CloseHandle = kernel32.CloseHandle
    EmptyWorkingSet = psapi.EmptyWorkingSet
    EmptyWorkingSet.argtypes = [ctypes.c_void_p]
    EmptyWorkingSet.restype = ctypes.c_bool

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_QUERY_INFORMATION = 0x0400

    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "").lower()
        if name in skip or should_skip_ram_trim(name):
            continue
        pid = proc.info.get("pid")
        if not pid:
            continue
        h = OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            continue
        try:
            if EmptyWorkingSet(h):
                count += 1
        except Exception:
            pass
        finally:
            CloseHandle(h)
    return count, errors


def clean_ram(
    *,
    gentle: bool = True,
    purge_standby: bool | None = None,
    purge_low_priority_standby: bool = True,
    empty_system_working_sets: bool | None = None,
    flush_modified: bool = True,
    trim_processes: bool = True,
) -> RamCleanReport:
    if purge_standby is None:
        purge_standby = not gentle
    if empty_system_working_sets is None:
        empty_system_working_sets = not gentle
    before = get_ram_stats()
    errors: list[str] = []
    standby_ok = False
    ws_ok = False
    mod_ok = False
    trimmed = 0

    def _err(label: str, ok: bool) -> None:
        if ok:
            return
        st = ntstatus_name(last_ntstatus())
        hint = "" if is_admin() else " (запусти run_admin.bat)"
        errors.append(f"{label}: {st}{hint}")

    if flush_modified:
        try:
            mod_ok = flush_modified_list()
            _err("FlushModifiedList", mod_ok)
        except OSError as e:
            errors.append(f"FlushModifiedList: {e}")

    if empty_system_working_sets:
        try:
            ws_ok = empty_all_working_sets()
            _err("EmptyWorkingSets", ws_ok)
        except OSError as e:
            errors.append(f"EmptyWorkingSets: {e}")

    if purge_low_priority_standby:
        try:
            purge_standby_lists(low_priority_only=True)
        except OSError as e:
            errors.append(f"PurgeLowPriorityStandby: {e}")

    if purge_standby:
        try:
            standby_ok = purge_standby_lists(low_priority_only=False)
            _err("PurgeStandby", standby_ok)
        except OSError as e:
            errors.append(f"PurgeStandby: {e}")

    flush_system_file_cache()

    if trim_processes:
        trimmed, trim_err = trim_process_working_sets(
            skip_names={"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe"}
        )
        errors.extend(trim_err)

    after = get_ram_stats()
    return RamCleanReport(
        standby_purged=standby_ok,
        working_sets_emptied=ws_ok,
        modified_flushed=mod_ok,
        processes_trimmed=trimmed,
        errors=errors,
        before=before,
        after=after,
    )

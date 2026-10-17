import subprocess
from dataclasses import dataclass
from pathlib import Path

from scalyclean.core.utils import CleanResult, clear_directory_contents, dir_size


@dataclass
class SystemMaintenanceResult:
    disk_results: list[CleanResult]
    dism_started: bool
    dism_errors: list[str]


def _windows_logs_size() -> int:
    windir = Path(r"C:\Windows")
    total = 0
    for sub in ("Logs", "Panther", "inf"):
        total += dir_size(windir / sub)
    return total


def clean_old_windows_logs(admin: bool) -> CleanResult:
    """Только *.log / *.old в Logs — не трогаем Panther (установка/восстановление)."""
    if not admin:
        return CleanResult("Старые логи Windows (*.log)", 0, 0, ["Нужен админ"])
    freed = 0
    count = 0
    errors: list[str] = []
    logs_dir = Path(r"C:\Windows\Logs")
    if not logs_dir.is_dir():
        return CleanResult("Старые логи Windows (*.log)", 0, 0, errors)
    for fp in logs_dir.rglob("*"):
        try:
            if fp.is_file() and fp.suffix.lower() in (".log", ".old", ".bak"):
                freed += fp.stat().st_size
                fp.unlink(missing_ok=True)
                count += 1
        except OSError as e:
            errors.append(f"{fp}: {e}")
    return CleanResult("Старые логи Windows (*.log)", freed, count, errors)


def start_dism_component_cleanup() -> tuple[bool, list[str]]:
    """DISM /StartComponentCleanup — освобождает WinSxS (долго, в фоне)."""
    errors: list[str] = []
    try:
        subprocess.Popen(
            [
                "dism.exe",
                "/Online",
                "/Cleanup-Image",
                "/StartComponentCleanup",
                "/ResetBase",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, errors
    except OSError as e:
        errors.append(str(e))
        return False, errors


def start_dism_analyze() -> list[str]:
    try:
        subprocess.Popen(
            ["dism.exe", "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return []
    except OSError as e:
        return [str(e)]

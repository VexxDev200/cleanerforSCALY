import ctypes
from pathlib import Path

from scalyclean.core.safety import guard_cleanup, path_exists_safe
from scalyclean.core.utils import CleanResult, clear_directory_contents, safe_remove_path
from scalyclean.modules.disk_targets import DiskTarget, all_disk_targets, scan_target_size


def scan_all(selected_ids: set[str] | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in all_disk_targets():
        if selected_ids is not None and t.id not in selected_ids:
            continue
        try:
            out[t.id] = scan_target_size(t)
        except (OSError, PermissionError):
            out[t.id] = 0
    return out


def clean_targets(
    selected_ids: set[str],
    *,
    admin: bool,
) -> list[CleanResult]:
    results: list[CleanResult] = []
    by_id = {t.id: t for t in all_disk_targets()}

    for tid in selected_ids:
        t = by_id.get(tid)
        if not t:
            continue
        if t.needs_admin and not admin:
            results.append(
                CleanResult(t.label, 0, 0, ["Нужны права администратора"])
            )
            continue

        freed, count, errors = _clean_one(t)
        results.append(CleanResult(t.label, freed, count, errors))
    return results


def _clean_one(t: DiskTarget) -> tuple[int, int, list[str]]:
    blocked = guard_cleanup(t.path, mode=t.mode, target_id=t.id)
    if blocked:
        return 0, 0, blocked

    if t.mode == "firefox_cache2":
        return _clean_firefox_cache2(t.path)

    if t.mode == "recycle":
        return _empty_recycle_bin()

    if t.mode == "pattern":
        return _clean_patterns(t.path, ("*.tmp", "*.part", "*.crdownload", "*.download"))

    if t.mode == "thumbcache":
        return _clean_thumbnail_cache(t.path)

    if not path_exists_safe(t.path):
        return 0, 0, []

    if t.mode == "contents":
        return clear_directory_contents(t.path)

    return safe_remove_path(t.path, remove_root=False)


def _clean_firefox_cache2(profiles_root: Path) -> tuple[int, int, list[str]]:
    freed = 0
    count = 0
    errors: list[str] = []
    if not profiles_root.is_dir():
        return 0, 0, errors
    for prof in profiles_root.iterdir():
        cache = prof / "cache2"
        if cache.is_dir():
            f, c, e = safe_remove_path(cache, remove_root=True)
            freed += f
            count += c
            errors.extend(e)
    return freed, count, errors


def _clean_thumbnail_cache(explorer_dir: Path) -> tuple[int, int, list[str]]:
    freed = 0
    count = 0
    errors: list[str] = []
    for pat in ("thumbcache_*.db", "iconcache_*.db"):
        for fp in explorer_dir.glob(pat):
            try:
                freed += fp.stat().st_size
                fp.unlink(missing_ok=True)
                count += 1
            except OSError as e:
                errors.append(f"{fp}: {e}")
    return freed, count, errors


def _clean_patterns(folder: Path, patterns: tuple[str, ...]) -> tuple[int, int, list[str]]:
    freed = 0
    count = 0
    errors: list[str] = []
    if not folder.is_dir():
        return 0, 0, errors
    for pat in patterns:
        for fp in folder.glob(pat):
            try:
                if fp.is_file():
                    freed += fp.stat().st_size
                    fp.unlink(missing_ok=True)
                    count += 1
            except OSError as e:
                errors.append(f"{fp}: {e}")
    return freed, count, errors


def _empty_recycle_bin() -> tuple[int, int, list[str]]:
    errors: list[str] = []
    try:
        shell32 = ctypes.windll.shell32
        flags = 0x00000007  # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        hr = shell32.SHEmptyRecycleBinW(None, None, flags)
        if hr != 0:
            errors.append(f"SHEmptyRecycleBin HRESULT={hr}")
    except OSError as e:
        errors.append(str(e))
    return 0, 0, errors


def run_disk_cleanup_sageset() -> list[str]:
    """Запуск встроенного cleanmgr (опционально, асинхронно в UI)."""
    import os
    import subprocess

    errors: list[str] = []
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    cleanmgr = windir / "System32" / "cleanmgr.exe"
    if not cleanmgr.exists():
        return ["cleanmgr.exe не найден"]
    try:
        subprocess.Popen(
            [str(cleanmgr), "/d", "C:"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as e:
        errors.append(str(e))
    return errors

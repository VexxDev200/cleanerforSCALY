"""Надёжное удаление на Windows: длинные пути, read-only, отчёт об ошибках."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import ctypes
from dataclasses import dataclass
from pathlib import Path

from scalyclean.core.utils import dir_size

MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
_WINERROR_SHARING = 32


@dataclass
class DeleteReport:
    path: Path
    success: bool
    bytes_freed: int
    errors: list[str]
    hint: str = ""


def to_extended_path(path: Path) -> str:
    p = str(path.resolve())
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def _chmod_writable(p: str) -> None:
    try:
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(p, 0x80)  # FILE_ATTRIBUTE_NORMAL
    except Exception:
        pass


def _rmtree_onerror(func, path, exc_info):
    _chmod_writable(path)
    try:
        func(path)
    except OSError:
        pass


def _rmtree_onexc(func, path, exc):
    _chmod_writable(path)
    try:
        func(path)
    except OSError:
        pass


def path_still_exists(path: Path) -> bool:
    try:
        return Path(to_extended_path(path)).exists()
    except OSError:
        try:
            return path.exists()
        except OSError:
            return True


def force_delete_tree(path: Path, *, expected_size: int = 0) -> DeleteReport:
    errors: list[str] = []
    if not path.exists() and not Path(to_extended_path(path)).exists():
        return DeleteReport(path, True, 0, [], "Уже удалено")

    size_before = expected_size if expected_size > 0 else dir_size(path)
    ext = to_extended_path(path)

    try:
        if path.is_file():
            _chmod_writable(ext)
            os.remove(ext)
        else:
            if sys.version_info >= (3, 12):
                shutil = __import__("shutil")
                shutil.rmtree(ext, onexc=_rmtree_onexc)
            else:
                shutil = __import__("shutil")
                shutil.rmtree(ext, onerror=_rmtree_onerror)
    except OSError as e:
        errors.append(str(e))

    if path_still_exists(path):
        # fallback: cmd rmdir
        try:
            subprocess.run(
                ["cmd", "/c", "rmdir", "/s", "/q", ext],
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=3600,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"rmdir: {e}")

    gone = not path_still_exists(path)
    freed = size_before if gone else 0
    hint = ""
    if not gone:
        hint = (
            "Папка осталась. Закрой Steam/игру, запусти SCALY от администратора "
            "(run_admin.bat) и повтори."
        )
        if errors:
            hint += f"\n{errors[0][:200]}"
    return DeleteReport(path, gone, freed, errors, hint)


def schedule_delete_on_reboot(path: str) -> bool:
    """Удалить файл после перезагрузки (нужен админ для системных путей)."""
    try:
        ext = path if path.startswith("\\\\?\\") else to_extended_path(Path(path))
        return bool(ctypes.windll.kernel32.MoveFileExW(ext, None, MOVEFILE_DELAY_UNTIL_REBOOT))
    except OSError:
        return False


@dataclass
class FolderCleanReport:
    bytes_freed: int
    files_removed: int
    files_locked: int
    scheduled_reboot: int
    notes: list[str]


def clear_folder_best_effort(path: Path, *, keep_root: bool = True) -> FolderCleanReport:
    """
    Удаляет всё, что не занято процессом.
    Занятые файлы — в очередь на удаление после перезагрузки (если получится).
    """
    freed = 0
    removed = 0
    locked = 0
    scheduled = 0
    notes: list[str] = []

    if not path.exists():
        return FolderCleanReport(0, 0, 0, 0, notes)

    if path.is_file():
        try:
            sz = path.stat().st_size
            os.remove(to_extended_path(path))
            return FolderCleanReport(sz, 1, 0, 0, notes)
        except OSError as e:
            if getattr(e, "winerror", None) == _WINERROR_SHARING:
                if schedule_delete_on_reboot(to_extended_path(path)):
                    scheduled = 1
                locked = 1
            notes.append("файл занят GPU/игрой")
            return FolderCleanReport(0, 0, locked, scheduled, notes)

    stack: list[Path] = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            ep = Path(entry.path)
            try:
                if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    try:
                        sz = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        sz = 0
                    ext = to_extended_path(ep)
                    try:
                        _chmod_writable(ext)
                        os.remove(ext)
                        freed += sz
                        removed += 1
                    except OSError as e:
                        if getattr(e, "winerror", None) == _WINERROR_SHARING:
                            locked += 1
                            if schedule_delete_on_reboot(ext):
                                scheduled += 1
                        else:
                            notes.append(f"{ep.name}: {e}")
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(ep)
            except OSError:
                continue

    # пустые папки снизу вверх
    for root, dirs, files in os.walk(path, topdown=False, onerror=lambda _: None):
        for name in dirs:
            dp = Path(root) / name
            try:
                dp.rmdir()
            except OSError:
                pass

    if not keep_root:
        rep = force_delete_tree(path)
        if rep.success:
            freed = max(freed, rep.bytes_freed)
        else:
            notes.append(rep.hint or "корень не удалён")

    if locked and not notes:
        notes.append(
            f"{locked} файлов заняты (NVIDIA/игра) — освобождено что можно; "
            f"перезагрузка снимет ещё {scheduled} в очереди"
        )
    return FolderCleanReport(freed, removed, locked, scheduled, notes)


def try_close_steam() -> list[str]:
    notes: list[str] = []
    for exe in ("steam.exe", "steamwebhelper.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
                capture_output=True,
            )
            notes.append(f"Остановлен {exe}")
        except (OSError, subprocess.TimeoutExpired):
            pass
    return notes

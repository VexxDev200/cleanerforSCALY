import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CleanResult:
    name: str
    bytes_freed: int
    files_removed: int
    errors: list[str]


def dir_size(path: Path) -> int:
    total = 0
    try:
        if not path.exists():
            return 0
    except (OSError, PermissionError):
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
        for root, _dirs, files in os.walk(path, topdown=True, onerror=lambda _: None):
            for f in files:
                fp = Path(root) / f
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def safe_remove_path(path: Path, *, remove_root: bool = True) -> tuple[int, int, list[str]]:
    from scalyclean.core.win_delete import force_delete_tree

    if not remove_root:
        return clear_directory_contents(path)
    rep = force_delete_tree(path)
    count = 1 if rep.success else 0
    return rep.bytes_freed, count, rep.errors + ([rep.hint] if rep.hint and not rep.success else [])


def clear_directory_contents(path: Path) -> tuple[int, int, list[str]]:
    freed = 0
    count = 0
    errors: list[str] = []
    try:
        if not path.is_dir():
            return 0, 0, errors
    except (OSError, PermissionError) as e:
        return 0, 0, [f"{path}: {e}"]
    try:
        for child in path.iterdir():
            if child.is_file() or child.is_symlink():
                try:
                    freed += child.stat().st_size
                    child.unlink(missing_ok=True)
                    count += 1
                except OSError as e:
                    errors.append(f"{child}: {e}")
            elif child.is_dir():
                f, c, e = safe_remove_path(child, remove_root=True)
                freed += f
                count += c
                errors.extend(e)
    except OSError as e:
        errors.append(f"{path}: {e}")
    return freed, count, errors


def format_bytes(n: int) -> str:
    if n < 0:
        n = 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.2f} PB"

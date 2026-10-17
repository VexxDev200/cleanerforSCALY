"""Только кэши/temp/мусор — никогда Program Files, игры, профили целиком."""

from pathlib import Path

# Если путь (нижний регистр) содержит это — не трогаем
_BLOCKED_FRAGMENTS = (
    "\\program files\\",
    "\\program files (x86)\\",
    "\\windows\\system32",
    "\\windows\\syswow64",
    "\\windows\\winsxs",
    "\\appdata\\local\\programs\\",  # установки пользователя (Discord app, etc.)
    "\\steam\\steamapps\\",
    "\\epic games\\",
    "\\riot games\\",
)

# Разрешены только если конечный путь подходит под один из маркеров
_ALLOWED_MARKERS = (
    "\\temp\\",
    "\\temp",
    "\\cache\\",
    "\\cache",
    "\\cache2",
    "\\inetcache",
    "\\d3dscache",
    "\\dxcache",
    "\\glcache",
    "\\shadercache",
    "\\htmlcache",
    "\\wer",
    "\\inetcache",
    "\\crashdumps",
    "\\thumbcache_",
    "\\iconcache_",
    "\\deliveryoptimization\\cache",
    "\\softwaredistribution\\download",
    "\\prefetch\\",
    "\\recycle",  # виртуальный
    "\\downloads\\",  # только pattern *.tmp
)


def path_exists_safe(path: Path) -> bool:
    if not path or str(path) in (".", ""):
        return False
    try:
        return path.exists()
    except (OSError, PermissionError):
        return False


def is_dir_safe(path: Path) -> bool:
    try:
        return path.is_dir()
    except (OSError, PermissionError):
        return False


def is_cleanup_path_allowed(path: Path, *, mode: str, target_id: str) -> bool:
    if mode == "recycle":
        return True
    if not path:
        return False
    try:
        resolved = str(path.resolve()).lower()
    except (OSError, PermissionError):
        return False

    for frag in _BLOCKED_FRAGMENTS:
        if frag in resolved:
            return False

    if mode in ("firefox_cache2",):
        return "\\mozilla\\firefox\\profiles" in resolved

    if mode == "thumbcache":
        return resolved.endswith("\\explorer") or "\\microsoft\\windows\\explorer" in resolved

    if mode == "pattern":
        return "\\downloads" in resolved

    for marker in _ALLOWED_MARKERS:
        if marker in resolved:
            return True

    # Жёсткий список id — если добавляешь цель, добавь маркер выше
    _ = target_id
    return False


def guard_cleanup(path: Path, *, mode: str, target_id: str) -> list[str]:
    if is_cleanup_path_allowed(path, mode=mode, target_id=target_id):
        return []
    return [f"Отклонено (безопасность): {path}"]

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiskTarget:
    id: str
    label: str
    path: Path
    mode: str  # "contents" | "tree" | "recycle"
    needs_admin: bool = False
    risky: bool = False


def _env(*keys: str) -> Path | None:
    for k in keys:
        v = os.environ.get(k)
        if v:
            return Path(v)
    return None


def targets_for_drive(drive: str) -> list[DiskTarget]:
    from scalyclean.modules.disk_analyzer import target_matches_drive

    out: list[DiskTarget] = []
    for t in all_disk_targets():
        if t.mode == "recycle":
            out.append(t)
        elif target_matches_drive(t.path, drive):
            out.append(t)
    return out


def all_disk_targets() -> list[DiskTarget]:
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    windir = os.environ.get("WINDIR", r"C:\Windows")
    programdata = os.environ.get("ProgramData", r"C:\ProgramData")

    targets: list[DiskTarget] = [
        DiskTarget("user_temp", "Temp пользователя", Path(local) / "Temp", "contents"),
        DiskTarget("win_temp", "Windows\\Temp", Path(windir) / "Temp", "contents", needs_admin=True),
        DiskTarget(
            "inet_cache",
            "Internet Cache (INetCache)",
            Path(local) / "Microsoft" / "Windows" / "INetCache",
            "contents",
        ),
        DiskTarget(
            "wer",
            "Отчёты об ошибках (WER)",
            Path(local) / "Microsoft" / "Windows" / "WER",
            "tree",
        ),
        DiskTarget(
            "crashdumps",
            "Local CrashDumps",
            Path(local) / "CrashDumps",
            "tree",
        ),
        DiskTarget(
            "thumbcache",
            "Кэш эскизов Explorer (только thumb/icon cache)",
            Path(local) / "Microsoft" / "Windows" / "Explorer",
            "thumbcache",
        ),
        DiskTarget(
            "d3d_shader",
            "DirectX Shader Cache (D3DSCache)",
            Path(local) / "D3DSCache",
            "tree",
        ),
        DiskTarget(
            "nv_dx",
            "NVIDIA DXCache",
            Path(local) / "NVIDIA" / "DXCache",
            "tree",
        ),
        DiskTarget(
            "nv_gl",
            "NVIDIA GLCache",
            Path(local) / "NVIDIA" / "GLCache",
            "tree",
        ),
        DiskTarget(
            "amd_dx",
            "AMD DXCache",
            Path(local) / "AMD" / "DxCache",
            "tree",
        ),
        DiskTarget(
            "chrome_cache",
            "Google Chrome — Cache",
            Path(local) / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
            "tree",
        ),
        DiskTarget(
            "edge_cache",
            "Microsoft Edge — Cache",
            Path(local) / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
            "tree",
        ),
        DiskTarget(
            "firefox_cache",
            "Firefox cache2 (профили)",
            Path(local) / "Mozilla" / "Firefox" / "Profiles",
            "firefox_cache2",
        ),
        DiskTarget(
            "discord_cache",
            "Discord Cache",
            Path(appdata) / "discord" / "Cache",
            "tree",
        ),
        DiskTarget(
            "steam_html",
            "Steam htmlcache",
            Path(programdata) / "Steam" / "htmlcache",
            "tree",
        ),
        DiskTarget(
            "delivery_opt",
            "Delivery Optimization (только с админом)",
            Path(windir) / "ServiceProfiles" / "NetworkService" / "AppData" / "Local" / "Microsoft" / "Windows" / "DeliveryOptimization" / "Cache",
            "tree",
            needs_admin=True,
            risky=True,
        ),
        DiskTarget(
            "wu_download",
            "Windows Update — SoftwareDistribution\\Download",
            Path(windir) / "SoftwareDistribution" / "Download",
            "contents",
            needs_admin=True,
            risky=True,
        ),
        DiskTarget(
            "prefetch",
            "Prefetch (*.pf)",
            Path(windir) / "Prefetch",
            "contents",
            needs_admin=True,
            risky=True,
        ),
        DiskTarget("recycle", "Корзина", Path(), "recycle"),
    ]

    downloads = Path(userprofile) / "Downloads" if userprofile else None
    if downloads:
        targets.append(
            DiskTarget(
                "downloads_temp",
                "Downloads — *.tmp / *.part",
                downloads,
                "pattern",
            )
        )

    extra = _env("TEMP")
    if extra and extra not in (str(Path(local) / "Temp"),):
        targets.append(DiskTarget("env_temp", "TEMP (env)", extra, "contents"))

    return targets


def scan_target_size(target: DiskTarget) -> int:
    from scalyclean.core.safety import path_exists_safe
    from scalyclean.core.utils import dir_size

    if target.mode == "firefox_cache2":
        return _firefox_cache2_size(target.path)
    if target.mode == "recycle":
        return _recycle_bin_size()
    if target.mode == "pattern":
        return _pattern_size(target.path, ("*.tmp", "*.part", "*.crdownload", "*.download"))
    if target.mode == "thumbcache":
        return _thumbcache_size(target.path)
    if not path_exists_safe(target.path):
        return 0
    if target.mode == "contents":
        total = 0
        try:
            for child in target.path.iterdir():
                total += dir_size(child)
        except (OSError, PermissionError):
            pass
        return total
    return dir_size(target.path)


def _thumbcache_size(explorer_dir: Path) -> int:
    total = 0
    try:
        if not explorer_dir.is_dir():
            return 0
        for pat in ("thumbcache_*.db", "iconcache_*.db"):
            for fp in explorer_dir.glob(pat):
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except (OSError, PermissionError):
        pass
    return total


def _firefox_cache2_size(profiles_root: Path) -> int:
    from scalyclean.core.utils import dir_size

    try:
        if not profiles_root.is_dir():
            return 0
    except (OSError, PermissionError):
        return 0
    total = 0
    try:
        for prof in profiles_root.iterdir():
            if prof.is_dir():
                total += dir_size(prof / "cache2")
    except (OSError, PermissionError):
        pass
    return total


def _pattern_size(folder: Path, patterns: tuple[str, ...]) -> int:
    if not folder.is_dir():
        return 0
    total = 0
    for pat in patterns:
        for p in folder.glob(pat):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return total


def _recycle_bin_size() -> int:
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_int64),
                ("i64NumItems", ctypes.c_int64),
            ]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        shell32 = ctypes.windll.shell32
        if shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.i64Size)
    except Exception:
        pass
    return 0

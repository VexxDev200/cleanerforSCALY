"""Поиск игр (Steam, Epic, GOG, Xbox, Riot, Battle.net) и кэшей лаунчеров."""

from __future__ import annotations

import json
import os
import re
import threading
import winreg
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from scalyclean.core.safety import path_exists_safe
from scalyclean.modules.disk_analyzer import folder_scan


@dataclass
class GameItem:
    uid: str
    name: str
    path: Path
    launcher: str
    size: int = 0
    file_count: int = 0
    deletable: bool = True
    note: str = ""


@dataclass
class LauncherCache:
    uid: str
    name: str
    path: Path
    launcher: str
    size: int = 0


# Только эти корни можно удалять целиком (игра)
_ALLOWED_GAME_ROOT_MARKERS = (
    "\\steamapps\\common\\",
    "\\steamlibrary\\",
    "\\fortnite\\",
    "\\epic games\\",
    "\\gog galaxy\\games\\",
    "\\riot games\\",
    "\\xboxgames\\",
    "\\battle.net\\",
    "\\ubisoft\\ubisoft game launcher\\cache\\",
    "\\electronic arts\\",
    "\\origin games\\",
    "\\ea games\\",
)


def is_safe_game_delete_path(path: Path) -> bool:
    try:
        low = str(path.resolve()).lower()
    except OSError:
        low = str(path).lower()
    if not low:
        return False
    if "\\windows\\" in low or "\\program files\\" in low and "steamapps" not in low:
        if "\\steamapps\\common\\" not in low:
            pass
    for m in _ALLOWED_GAME_ROOT_MARKERS:
        if m in low:
            return True
    # Steam common явно
    if "\\steamapps\\common\\" in low:
        return True
    return False


def _reg_path(key: str, value: str) -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            data, _ = winreg.QueryValueEx(k, value)
            if data:
                return Path(str(data))
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            data, _ = winreg.QueryValueEx(k, value)
            if data:
                return Path(str(data))
    except OSError:
        pass
    return None


def _steam_install() -> Path | None:
    p = _reg_path(r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")
    if p and p.is_dir():
        return p
    for guess in (
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam",
    ):
        if guess.is_dir():
            return guess
    return None


def _steam_libraries(steam: Path) -> list[Path]:
    libs = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for raw in re.findall(r'"path"\s+"([^"]+)"', text):
                p = Path(raw.replace("\\\\", "\\"))
                if p.is_dir() and p not in libs:
                    libs.append(p)
        except OSError:
            pass
    return libs


def _steam_manifest_sizes() -> dict[str, int]:
    """Мгновенно: installdir (lower) -> SizeOnDisk из appmanifest_*.acf."""
    out: dict[str, int] = {}
    steam = _steam_install()
    if not steam:
        return out
    for lib in _steam_libraries(steam):
        sap = lib / "steamapps"
        if not sap.is_dir():
            continue
        for acf in sap.glob("appmanifest_*.acf"):
            try:
                text = acf.read_text(encoding="utf-8", errors="ignore")
                m_dir = re.search(r'"installdir"\s+"([^"]+)"', text, re.I)
                m_sz = re.search(r'"SizeOnDisk"\s+"(\d+)"', text, re.I)
                if m_dir and m_sz:
                    out[m_dir.group(1).lower()] = int(m_sz.group(1))
            except OSError:
                continue
    return out


def _epic_path_sizes() -> dict[str, int]:
    out: dict[str, int] = {}
    manifest_dir = (
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Epic"
        / "EpicGamesLauncher"
        / "Data"
        / "Manifests"
    )
    if not manifest_dir.is_dir():
        return out
    for mf in manifest_dir.glob("*.item"):
        try:
            data = json.loads(mf.read_text(encoding="utf-8", errors="ignore"))
            loc = (data.get("InstallLocation") or "").strip()
            size = int(data.get("InstallSize") or data.get("ManifestSize") or data.get("DiskSize") or 0)
            if loc and size > 0:
                out[str(Path(loc)).lower()] = size
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            continue
    return out


def apply_known_sizes(games: list[GameItem]) -> None:
    steam = _steam_manifest_sizes()
    epic = _epic_path_sizes()
    for g in games:
        if g.size > 0:
            continue
        if g.launcher == "Steam":
            sz = steam.get(g.path.name.lower())
            if sz:
                g.size = sz
                g.note = "Steam manifest"
        elif g.launcher == "Epic":
            sz = epic.get(str(g.path).lower())
            if sz:
                g.size = sz
                g.note = "Epic manifest"


def _scan_steam_games() -> list[GameItem]:
    steam = _steam_install()
    if not steam:
        return []
    items: list[GameItem] = []
    for lib in _steam_libraries(steam):
        common = lib / "steamapps" / "common"
        if not common.is_dir():
            continue
        try:
            for child in common.iterdir():
                if child.is_dir():
                    items.append(
                        GameItem(
                            uid=f"steam:{child.name}",
                            name=child.name,
                            path=child,
                            launcher="Steam",
                        )
                    )
        except OSError:
            continue
    return items


def _scan_epic_games() -> list[GameItem]:
    items: list[GameItem] = []
    manifest_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if manifest_dir.is_dir():
        for mf in manifest_dir.glob("*.item"):
            try:
                data = json.loads(mf.read_text(encoding="utf-8", errors="ignore"))
                name = data.get("DisplayName") or data.get("AppName") or mf.stem
                install = data.get("InstallLocation") or ""
                if install:
                    p = Path(install)
                    if p.is_dir():
                        items.append(GameItem(uid=f"epic:{p.name}", name=str(name), path=p, launcher="Epic"))
            except (json.JSONDecodeError, OSError):
                continue
    for root in (
        Path(r"C:\Program Files\Epic Games"),
        Path(r"C:\Program Files (x86)\Epic Games"),
    ):
        if not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if child.is_dir() and not any(g.path == child for g in items):
                    items.append(
                        GameItem(uid=f"epicdir:{child.name}", name=child.name, path=child, launcher="Epic")
                    )
        except OSError:
            pass
    return items


def _scan_gog_games() -> list[GameItem]:
    items: list[GameItem] = []
    for root in (
        Path(r"C:\GOG Games"),
        Path(r"C:\Program Files (x86)\GOG Galaxy\Games"),
        Path(r"C:\Program Files\GOG Galaxy\Games"),
    ):
        if not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if child.is_dir():
                    items.append(GameItem(uid=f"gog:{child.name}", name=child.name, path=child, launcher="GOG"))
        except OSError:
            pass
    return items


def _scan_riot_games() -> list[GameItem]:
    items: list[GameItem] = []
    root = Path(r"C:\Riot Games")
    if not root.is_dir():
        return items
    try:
        for child in root.iterdir():
            if child.is_dir():
                items.append(GameItem(uid=f"riot:{child.name}", name=child.name, path=child, launcher="Riot"))
    except OSError:
        pass
    return items


def _scan_xbox_games() -> list[GameItem]:
    items: list[GameItem] = []
    root = Path(r"C:\XboxGames")
    if not root.is_dir():
        return items
    try:
        for child in root.iterdir():
            if child.is_dir():
                items.append(GameItem(uid=f"xbox:{child.name}", name=child.name, path=child, launcher="Xbox"))
    except OSError:
        pass
    return items


def discover_games() -> list[GameItem]:
    seen: set[str] = set()
    out: list[GameItem] = []
    for fn in (_scan_steam_games, _scan_epic_games, _scan_gog_games, _scan_riot_games, _scan_xbox_games):
        for g in fn():
            key = str(g.path).lower()
            if key in seen:
                continue
            seen.add(key)
            if not path_exists_safe(g.path):
                continue
            g.deletable = is_safe_game_delete_path(g.path)
            if not g.deletable:
                g.note = "ручной путь — проверь"
            out.append(g)
    apply_known_sizes(out)
    out.sort(key=lambda x: (-x.size, x.name.lower()))
    return out


def discover_launcher_caches() -> list[LauncherCache]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    caches = [
        ("Steam download", local / "Steam" / "htmlcache", "Steam"),
        ("Epic webcache", local / "EpicGamesLauncher" / "Saved" / "webcache", "Epic"),
        ("Battle.net Cache", local / "Battle.net" / "Cache", "Battle.net"),
        ("Riot Client Logs", local / "Riot Games" / "Riot Client" / "Logs", "Riot"),
        ("Ubisoft cache", local / "Ubisoft Game Launcher" / "cache", "Ubisoft"),
    ]
    out: list[LauncherCache] = []
    for name, path, launcher in caches:
        if path.is_dir():
            out.append(LauncherCache(uid=f"cache:{launcher}:{name}", name=name, path=path, launcher=launcher))
    return out


def measure_game(g: GameItem, cancel: threading.Event | None = None) -> None:
    try:
        r = folder_scan(g.path, cancel=cancel, collect_extensions=False)
        g.size = r.size
        g.file_count = r.file_count
    except OSError:
        g.size = 0


def measure_cache(c: LauncherCache, cancel: threading.Event | None = None) -> None:
    try:
        r = folder_scan(c.path, cancel=cancel, collect_extensions=False)
        c.size = r.size
    except OSError:
        c.size = 0


def measure_items(
    games: list[GameItem],
    caches: list[LauncherCache],
    cancel: threading.Event | None = None,
    on_one: Callable[[object], None] | None = None,
    *,
    games_to_measure: list[GameItem] | None = None,
) -> None:
    targets = games_to_measure if games_to_measure is not None else games
    for g in targets:
        if cancel and cancel.is_set():
            break
        measure_game(g, cancel=cancel)
        if on_one:
            on_one(g)
    if games_to_measure is None:
        for c in caches:
            if cancel and cancel.is_set():
                break
            measure_cache(c, cancel=cancel)
            if on_one:
                on_one(c)

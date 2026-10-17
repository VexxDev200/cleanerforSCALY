"""Проверка и установка обновлений для собранного exe (PyInstaller и аналоги)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from scalyclean import __version__
from scalyclean.core.update_config import DEFAULT_RELEASE_EXE_NAME, UPDATE_MANIFEST_URL

ProgressCallback = Callable[[int, int | None], None]  # bytes_done, bytes_total or None


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    notes: str
    file_name: str
    sha256: str | None = None


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def running_executable() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def parse_version(text: str) -> tuple[int, ...]:
    s = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in re.split(r"[.\-+]", s):
        if not chunk:
            continue
        m = re.match(r"^(\d+)", chunk)
        if not m:
            break
        parts.append(int(m.group(1)))
    return tuple(parts) if parts else (0,)


def version_gt(remote: str, local: str) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    a_p = a + (0,) * (n - len(a))
    b_p = b + (0,) * (n - len(b))
    return a_p > b_p


def resolve_manifest_url() -> str | None:
    env = os.environ.get("SCALY_UPDATE_MANIFEST_URL", "").strip()
    if env:
        return env
    exe_dir = running_executable().parent
    sidecar = exe_dir / "update_url.txt"
    if sidecar.is_file():
        line = sidecar.read_text(encoding="utf-8", errors="ignore").strip()
        if line.startswith("http"):
            return line
    url = UPDATE_MANIFEST_URL.strip()
    if url.startswith("http"):
        return url
    return None


def _parse_manifest_data(data: dict, base_dir: Path | None) -> UpdateInfo | None:
    ver = str(data.get("version", "")).strip()
    dl = str(data.get("download_url", "")).strip()
    if not ver or not dl:
        return None
    notes = str(data.get("notes", "") or "").strip()
    file_name = str(data.get("file_name", "") or DEFAULT_RELEASE_EXE_NAME).strip()
    sha = data.get("sha256")
    sha256 = str(sha).strip().lower() if sha else None
    if sha256 == "":
        sha256 = None
    if not dl.startswith("http"):
        root = base_dir or running_executable().parent
        dl = str((root / dl).resolve())
    return UpdateInfo(
        version=ver,
        download_url=dl,
        notes=notes,
        file_name=file_name or DEFAULT_RELEASE_EXE_NAME,
        sha256=sha256,
    )


def _load_manifest_bytes(raw: bytes, base_dir: Path | None) -> UpdateInfo | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return _parse_manifest_data(data, base_dir)


def fetch_manifest(timeout: float = 20.0) -> UpdateInfo | None:
    exe_dir = running_executable().parent
    local = exe_dir / "version.json"
    if local.is_file():
        try:
            info = _load_manifest_bytes(local.read_bytes(), exe_dir)
            if info:
                return info
        except OSError:
            pass

    url = resolve_manifest_url()
    if not url:
        return None
    if url.startswith("file:"):
        try:
            path = Path(urlparse(url).path)
            if path.is_file():
                return _load_manifest_bytes(path.read_bytes(), path.parent)
        except OSError:
            return None
        return None

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"SCALY-Cleaner/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return _load_manifest_bytes(raw, exe_dir)


def check_for_update() -> UpdateInfo | None:
    manifest = fetch_manifest()
    if manifest is None:
        return None
    if version_gt(manifest.version, __version__):
        return manifest
    return None


def _verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def _is_local_path(url: str) -> bool:
    if url.startswith("\\\\") or (len(url) > 2 and url[1] == ":"):
        return True
    return Path(url).exists()


def download_file(
    url: str,
    dest: Path,
    on_progress: ProgressCallback | None = None,
    timeout: float = 300.0,
) -> None:
    if _is_local_path(url):
        src = Path(url)
        if not src.is_file():
            raise FileNotFoundError(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = src.stat().st_size
        done = 0
        with src.open("rb") as inp, dest.open("wb") as out:
            while True:
                chunk = inp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        return

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"SCALY-Cleaner/{__version__}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = resp.headers.get("Content-Length")
        total_i = int(total) if total and total.isdigit() else None
        done = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total_i)


def _write_apply_batch(target: Path, downloaded: Path, pid: int) -> Path:
    bat = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".bat",
        delete=False,
        prefix="scaly_update_",
    )
    bat_path = Path(bat.name)
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "TARGET={target}"',
        f'set "NEW={downloaded}"',
        f'set "PID={pid}"',
        ":waitproc",
        'tasklist /FI "PID eq %PID%" 2>nul | find /I "%PID%" >nul',
        "if %ERRORLEVEL%==0 (timeout /t 1 /nobreak >nul & goto waitproc)",
        'if exist "%TARGET%.bak" del /F /Q "%TARGET%.bak"',
        'if exist "%TARGET%" move /Y "%TARGET%" "%TARGET%.bak"',
        'move /Y "%NEW%" "%TARGET%"',
        'start "" "%TARGET%"',
        'del /F /Q "%~f0"',
    ]
    bat.write("\r\n".join(lines) + "\r\n")
    bat.close()
    return bat_path


def apply_downloaded_update(downloaded: Path, target: Path | None = None) -> None:
    target = (target or running_executable()).resolve()
    downloaded = downloaded.resolve()
    if not downloaded.is_file():
        raise FileNotFoundError(downloaded)
    bat = _write_apply_batch(target, downloaded, os.getpid())
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat)],
        close_fds=True,
        creationflags=flags,
    )
    sys.exit(0)


def install_update(
    info: UpdateInfo,
    on_progress: ProgressCallback | None = None,
) -> None:
    tmp_dir = Path(tempfile.gettempdir()) / "ScalyCleaner_update"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / info.file_name
    if dest.is_file():
        try:
            dest.unlink()
        except OSError:
            pass
    download_file(info.download_url, dest, on_progress=on_progress)
    if info.sha256 and not _verify_sha256(dest, info.sha256):
        try:
            dest.unlink()
        except OSError:
            pass
        raise ValueError("SHA256 не совпал — обновление отменено")
    apply_downloaded_update(dest)

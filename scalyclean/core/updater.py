"""Проверка и установка обновлений для собранного exe (PyInstaller и аналоги)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from scalyclean import __version__
from scalyclean.core.update_config import (
    DEFAULT_RELEASE_EXE_NAME,
    UPDATE_MANIFEST_URL,
    github_repo_slug,
)

ProgressCallback = Callable[[int, int | None], None]  # bytes_done, bytes_total or None

# Как часто exe спрашивает GitHub (мс / сек)
UPDATE_POLL_MS = 60_000
UPDATE_MIN_GAP_SEC = 20
UPDATE_NETWORK_TIMEOUT = 12.0


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    notes: str
    file_name: str
    sha256: str | None = None
    source: str = "remote"


@dataclass
class UpdateDiagnosis:
    local_version: str
    manifest_url: str | None
    manifest_source: str
    remote_version: str | None
    update_available: bool
    download_reachable: bool
    download_bytes: int | None
    errors: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return self.public_summary_lines(include_debug=True)

    def public_summary_lines(self, include_debug: bool = False) -> list[str]:
        lines = [
            f"Твоя версия: v{self.local_version}",
            f"На сервере: v{self.remote_version or '—'}",
        ]
        if self.update_available:
            lines.append("Доступно обновление — нажми «Обновить» в шапке.")
        else:
            lines.append("Установлена последняя версия.")
        if include_debug:
            lines.append(f"Источник: {self.manifest_source}")
            lines.append(f"Ссылка на exe: {'OK' if self.download_reachable else 'нет'}")
            if self.download_bytes is not None:
                lines.append(f"Размер: {self.download_bytes} байт")
            for e in self.errors:
                lines.append(f"! {e}")
        return lines


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
        source="local",
    )


def _load_manifest_bytes(raw: bytes, base_dir: Path | None) -> UpdateInfo | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return _parse_manifest_data(data, base_dir)


def effective_local_version() -> str:
    override = os.environ.get("SCALY_UPDATE_TEST_VERSION", "").strip()
    if override:
        return override
    return __version__


def _fetch_local_manifest(exe_dir: Path) -> UpdateInfo | None:
    local = exe_dir / "version.json"
    if not local.is_file():
        return None
    try:
        info = _load_manifest_bytes(local.read_bytes(), exe_dir)
        if info:
            return UpdateInfo(
                version=info.version,
                download_url=info.download_url,
                notes=info.notes,
                file_name=info.file_name,
                sha256=info.sha256,
                source="local",
            )
    except OSError:
        pass
    return None


_GH_RAW = re.compile(
    r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+?)$"
)


def _fetch_github_api_manifest(url: str, timeout: float) -> bytes | None:
    m = _GH_RAW.match(url.split("?", 1)[0])
    if not m:
        return None
    user, repo, branch, path = m.groups()
    api = (
        f"https://api.github.com/repos/{user}/{repo}/contents/{path}?ref={branch}"
    )
    req = urllib.request.Request(
        api,
        headers={
            "User-Agent": f"SCALY-Cleaner/{__version__}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = str(payload.get("content", "")).replace("\n", "")
        if payload.get("encoding") == "base64" and content:
            return base64.b64decode(content)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    return None


def _fetch_remote_manifest(
    url: str, exe_dir: Path, timeout: float
) -> tuple[UpdateInfo | None, str | None]:
    if url.startswith("file:"):
        try:
            path = Path(urlparse(url).path)
            if path.is_file():
                info = _load_manifest_bytes(path.read_bytes(), path.parent)
                if info:
                    return (
                        UpdateInfo(
                            version=info.version,
                            download_url=info.download_url,
                            notes=info.notes,
                            file_name=info.file_name,
                            sha256=info.sha256,
                            source="remote",
                        ),
                        None,
                    )
        except OSError as e:
            return None, str(e)
        return None, "file manifest missing"

    raw = _fetch_github_api_manifest(url, timeout)
    if raw is None:
        bust = url if "?" in url else f"{url}?t={int(time.time())}"
        req = urllib.request.Request(
            bust,
            headers={
                "User-Agent": f"SCALY-Cleaner/{__version__}",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return None, str(e)
    info = _load_manifest_bytes(raw, exe_dir)
    if not info:
        return None, "invalid manifest json"
    return (
        UpdateInfo(
            version=info.version,
            download_url=info.download_url,
            notes=info.notes,
            file_name=info.file_name,
            sha256=info.sha256,
            source="remote",
        ),
        None,
    )


def fetch_github_latest_release(timeout: float = 20.0) -> UpdateInfo | None:
    slug = github_repo_slug()
    if not slug:
        return None
    user, repo = slug
    api = f"https://api.github.com/repos/{user}/{repo}/releases/latest"
    req = urllib.request.Request(
        api,
        headers={
            "User-Agent": f"SCALY-Cleaner/{__version__}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    tag = str(data.get("tag_name", "")).strip()
    ver = tag.lstrip("vV")
    if not ver:
        return None
    exe_name = DEFAULT_RELEASE_EXE_NAME
    download_url = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.lower() == exe_name.lower():
            download_url = str(asset.get("browser_download_url", ""))
            break
    if not download_url:
        for asset in data.get("assets") or []:
            if str(asset.get("name", "")).lower().endswith(".exe"):
                download_url = str(asset.get("browser_download_url", ""))
                break
    if not download_url.startswith("http"):
        return None
    notes = str(data.get("body") or data.get("name") or "").strip()[:800]
    return UpdateInfo(
        version=ver,
        download_url=download_url,
        notes=notes,
        file_name=exe_name,
        sha256=None,
        source="github-release",
    )


def _fetch_manifest_json_remote(timeout: float) -> tuple[UpdateInfo | None, str | None]:
    exe_dir = running_executable().parent
    url = resolve_manifest_url()
    if not url:
        return None, "no manifest url"
    raw = _fetch_github_api_manifest(url, timeout)
    if raw is None:
        remote, err = _fetch_remote_manifest(url, exe_dir, timeout)
        return remote, err
    info = _load_manifest_bytes(raw, exe_dir)
    if not info:
        return None, "invalid manifest"
    return (
        UpdateInfo(
            version=info.version,
            download_url=info.download_url,
            notes=info.notes,
            file_name=info.file_name,
            sha256=info.sha256,
            source="manifest",
        ),
        None,
    )


def _pick_newest(*items: UpdateInfo | None) -> UpdateInfo | None:
    best: UpdateInfo | None = None
    for info in items:
        if info is None:
            continue
        if best is None or version_gt(info.version, best.version):
            best = info
    return best


def fetch_best_available_update(timeout: float = UPDATE_NETWORK_TIMEOUT) -> UpdateInfo | None:
    from concurrent.futures import ThreadPoolExecutor

    release: UpdateInfo | None = None
    manifest: UpdateInfo | None = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_rel = pool.submit(fetch_github_latest_release, timeout)
        f_man = pool.submit(_fetch_manifest_json_remote, timeout)
        release = f_rel.result()
        manifest, _err = f_man.result()
    best = _pick_newest(release, manifest)
    if best:
        return best
    if is_frozen_app():
        return None
    return _fetch_local_manifest(running_executable().parent)


def fetch_manifest(timeout: float = 20.0) -> UpdateInfo | None:
    return fetch_best_available_update(timeout)


def probe_download(url: str, timeout: float = 25.0) -> tuple[bool, int | None, str | None]:
    if _is_local_path(url):
        p = Path(url)
        if p.is_file():
            return True, p.stat().st_size, None
        return False, None, "local file missing"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"SCALY-Cleaner/{__version__}",
            "Range": "bytes=0-0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cr = resp.headers.get("Content-Range", "")
            if "/" in cr:
                total = cr.split("/")[-1].strip()
                if total.isdigit():
                    return True, int(total), None
            size = resp.headers.get("Content-Length")
            if size and size.isdigit():
                n = int(size)
                if n > 1:
                    return True, n, None
            return True, None, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None, "HTTP 404"
        return False, None, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, None, str(e)


def diagnose_update(timeout: float = 20.0) -> UpdateDiagnosis:
    local = effective_local_version()
    exe_dir = running_executable().parent
    url = resolve_manifest_url()
    slug = github_repo_slug()
    release_api = (
        f"https://api.github.com/repos/{slug[0]}/{slug[1]}/releases/latest"
        if slug
        else None
    )
    errors: list[str] = []
    manifest: UpdateInfo | None = None
    source = "none"

    release = fetch_github_latest_release(timeout)
    manifest_json, m_err = _fetch_manifest_json_remote(timeout)
    manifest = _pick_newest(release, manifest_json)
    if manifest:
        source = manifest.source
    else:
        if m_err:
            errors.append(m_err)
        if release_api:
            errors.append("github releases unavailable")

    if manifest is None and not is_frozen_app():
        manifest = _fetch_local_manifest(exe_dir)
        if manifest:
            source = "local"
    if manifest is None:
        errors.append("update source not found")

    remote_ver = manifest.version if manifest else None
    need = bool(manifest and version_gt(manifest.version, local))
    dl_ok = False
    dl_size: int | None = None
    if manifest:
        dl_ok, dl_size, dl_err = probe_download(manifest.download_url, timeout)
        if dl_err:
            errors.append(f"download: {dl_err}")

    return UpdateDiagnosis(
        local_version=local,
        manifest_url=release_api or url,
        manifest_source=source,
        remote_version=remote_ver,
        update_available=need,
        download_reachable=dl_ok,
        download_bytes=dl_size,
        errors=errors,
    )


def check_for_update() -> UpdateInfo | None:
    manifest = fetch_manifest()
    if manifest is None:
        return None
    if version_gt(manifest.version, effective_local_version()):
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

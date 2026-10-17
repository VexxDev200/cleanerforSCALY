"""
Сборка portable + version.json + (опционально) GitHub Release.
Запуск из корня: python tools/build_release.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.integrity_manifest import write_integrity_module  # noqa: E402


def load_settings() -> dict:
    p = ROOT / "release_settings.json"
    return json.loads(p.read_text(encoding="utf-8"))


def read_version() -> str:
    text = (ROOT / "scalyclean" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("Missing __version__ in scalyclean/__init__.py")
    return m.group(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_url(settings: dict) -> str:
    user = settings.get("github_user", "").strip()
    repo = settings.get("github_repo", "").strip()
    branch = settings.get("branch", "main").strip() or "main"
    if user and repo:
        return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/releases/version.json"
    return ""


def github_release_download_url(settings: dict, version: str, exe_name: str) -> str:
    user = settings["github_user"].strip()
    repo = settings["github_repo"].strip()
    tag = f"v{version}"
    return f"https://github.com/{user}/{repo}/releases/download/{tag}/{exe_name}"


def run_build() -> Path:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt", "pyinstaller"],
        cwd=ROOT,
    )
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "ScalyCleaner.spec"],
        cwd=ROOT,
    )
    exe = ROOT / "dist" / "ScalyCleaner.exe"
    if not exe.is_file():
        raise SystemExit("Build failed: dist/ScalyCleaner.exe missing")
    return exe


def write_manifest(version: str, settings: dict, sha: str) -> dict:
    exe_name = settings.get("exe_name", "ScalyCleaner.exe")
    payload = {
        "version": version,
        "download_url": github_release_download_url(settings, version, exe_name),
        "file_name": exe_name,
        "notes": settings.get("release_notes", ""),
        "sha256": sha,
    }
    rel = ROOT / "releases" / "version.json"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def make_release_zip(exe: Path, manifest: dict) -> Path:
    """Только один exe в ZIP — пользователям не нужны sidecar-файлы."""
    zip_path = ROOT / "dist" / f"ScalyCleaner-v{manifest['version']}-win64.zip"
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, arcname=manifest["file_name"])
    legacy = ROOT / "dist" / "ScalyCleaner-portable"
    if legacy.is_dir():
        shutil.rmtree(legacy, ignore_errors=True)
    return zip_path


def try_github_release(exe: Path, manifest: dict, settings: dict) -> None:
    import os

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN not set — skip GitHub release (local artifacts OK).")
        return
    gh = shutil.which("gh")
    if not gh:
        print("gh CLI not found — install GitHub CLI or upload dist manually.")
        return
    version = manifest["version"]
    tag = f"v{version}"
    repo = f"{settings['github_user']}/{settings['github_repo']}"
    env = {**os.environ, "GH_TOKEN": token}
    view = subprocess.run(
        [gh, "release", "view", tag, "-R", repo],
        env=env,
        cwd=ROOT,
        capture_output=True,
    )
    if view.returncode != 0:
        subprocess.check_call(
            [
                gh,
                "release",
                "create",
                tag,
                "-R",
                repo,
                "--title",
                f"SCALY Cleaner {tag}",
                "--notes",
                manifest.get("notes") or tag,
                str(exe),
            ],
            env=env,
            cwd=ROOT,
        )
    else:
        subprocess.check_call(
            [gh, "release", "upload", tag, str(exe), "-R", repo, "--clobber"],
            env=env,
            cwd=ROOT,
        )
    print(f"GitHub Release {tag}: https://github.com/{repo}/releases/tag/{tag}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    settings = load_settings()
    version = read_version()
    print(f"Build SCALY Cleaner v{version}...")
    subprocess.check_call([sys.executable, str(ROOT / "tools" / "generate_brand_assets.py")], cwd=ROOT)
    write_integrity_module()
    exe = run_build()
    sha = sha256_file(exe)
    manifest = write_manifest(version, settings, sha)
    zip_path = make_release_zip(exe, manifest)
    print(f"EXE: {exe}")
    print(f"ZIP: {zip_path}")
    print(f"Manifest: {ROOT / 'releases' / 'version.json'}")
    print(f"SHA256: {sha}")
    print("After release: git add releases/version.json && git commit && git push origin main")
    print("Verify: python tools/verify_auto_update.py")
    try_github_release(exe, manifest, settings)


if __name__ == "__main__":
    main()

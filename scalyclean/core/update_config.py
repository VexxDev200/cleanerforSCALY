"""URL manifest для автообновления (из release_settings.json в сборке)."""

import json
import sys
from pathlib import Path

DEFAULT_RELEASE_EXE_NAME = "ScalyCleaner.exe"

_FALLBACK_MANIFEST = (
    "https://raw.githubusercontent.com/VexxDev200/cleanerforSCALY/main/releases/version.json"
)


def _settings_path() -> Path | None:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "release_settings.json"
            if p.is_file():
                return p
    root = Path(__file__).resolve().parents[2]
    p = root / "release_settings.json"
    return p if p.is_file() else None


def load_release_settings() -> dict:
    p = _settings_path()
    if not p:
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def manifest_url_from_settings(settings: dict) -> str:
    user = str(settings.get("github_user", "")).strip()
    repo = str(settings.get("github_repo", "")).strip()
    branch = str(settings.get("branch", "main")).strip() or "main"
    if user and repo:
        return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/releases/version.json"
    return _FALLBACK_MANIFEST


UPDATE_MANIFEST_URL = manifest_url_from_settings(load_release_settings())

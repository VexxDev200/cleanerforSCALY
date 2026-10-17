"""
Background: after you save files, auto git push (no manual commands).
Start once: pythonw tools/auto_deploy_watcher.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH_DIRS = [
    ROOT / "scalyclean",
    ROOT / "assets",
    ROOT / ".github" / "workflows",
]
WATCH_FILES = [ROOT / "main.py", ROOT / "requirements.txt", ROOT / "ScalyCleaner.spec"]

POLL_SEC = 8
QUIET_AFTER_CHANGE_SEC = 45


def _snapshot() -> str:
    h = hashlib.sha256()
    for d in WATCH_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                try:
                    h.update(p.as_posix().encode())
                    h.update(str(p.stat().st_mtime_ns).encode())
                except OSError:
                    pass
    for f in WATCH_FILES:
        if f.is_file():
            try:
                h.update(f.as_posix().encode())
                h.update(str(f.stat().st_mtime_ns).encode())
            except OSError:
                pass
    return h.hexdigest()


def main() -> None:
    sig = _snapshot()
    pending_since: float | None = None
    while True:
        time.sleep(POLL_SEC)
        cur = _snapshot()
        if cur != sig:
            sig = cur
            pending_since = time.time()
            continue
        if pending_since is None:
            continue
        if time.time() - pending_since < QUIET_AFTER_CHANGE_SEC:
            continue
        pending_since = None
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "auto_deploy.py")],
            cwd=ROOT,
        )


if __name__ == "__main__":
    main()

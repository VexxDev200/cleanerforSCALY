"""
Commit + push to origin/main (triggers GitHub Actions -> new exe for all users).
Usage: python tools/auto_deploy.py
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WATCH_PREFIXES = (
    "scalyclean/",
    "main.py",
    "requirements.txt",
    "assets/",
    "ScalyCleaner.spec",
    "tools/build_release.py",
    "tools/integrity_manifest.py",
    ".github/workflows/",
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _relevant_changes(porcelain: str) -> bool:
    for line in porcelain.splitlines():
        path = line[3:].strip() if len(line) > 3 else ""
        if any(path.replace("\\", "/").startswith(p) for p in WATCH_PREFIXES):
            return True
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not (ROOT / ".git").is_dir():
        print("auto_deploy: not a git repo")
        return 1

    st = _run(["git", "status", "--porcelain"])
    if st.returncode != 0:
        print(st.stderr or st.stdout)
        return st.returncode

    if not st.stdout.strip():
        print("auto_deploy: nothing to push")
        return 0

    if not _relevant_changes(st.stdout):
        print("auto_deploy: only non-release files changed, skip")
        return 0

    paths_to_add: list[str] = []
    for line in st.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().replace("\\", "/")
        if path == "releases/version.json":
            continue
        if any(path.startswith(p.rstrip("/")) or path == p.rstrip("/") for p in WATCH_PREFIXES):
            paths_to_add.append(path)
    if not paths_to_add:
        print("auto_deploy: no release-tracked paths to commit")
        return 0

    add = _run(["git", "add", "--"] + paths_to_add)
    if add.returncode != 0:
        print(add.stderr)
        return add.returncode

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = f"auto: deploy {ts}"
    commit = _run(["git", "commit", "-m", msg])
    if commit.returncode != 0:
        if "nothing to commit" in (commit.stdout + commit.stderr).lower():
            print("auto_deploy: nothing to commit")
            return 0
        print(commit.stderr or commit.stdout)
        return commit.returncode

    push = _run(["git", "push", "origin", "main"])
    if push.returncode != 0:
        print(push.stderr or push.stdout)
        return push.returncode

    print("auto_deploy: pushed to main — GitHub Actions will build release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Поднять patch-версию в scalyclean/__init__.py перед релизом."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scalyclean" / "__init__.py"


def read_version() -> str:
    text = INIT.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("version not found")
    return m.group(1)


def bump_patch(ver: str) -> str:
    parts = ver.split(".")
    while len(parts) < 3:
        parts.append("0")
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts[:3])


def write_version(ver: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    text, n = re.subn(
        r'(__version__\s*=\s*["\'])([^"\']+)(["\'])',
        rf'\g<1>{ver}\g<3>',
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit("could not write version")
    INIT.write_text(text, encoding="utf-8")


def main() -> None:
    cur = read_version()
    new = bump_patch(cur)
    write_version(new)
    print(new)


if __name__ == "__main__":
    main()

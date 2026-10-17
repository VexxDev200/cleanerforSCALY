"""CI: bump patch version before automated build."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.bump_version import bump_patch, read_version, write_version

if __name__ == "__main__":
    new = bump_patch(read_version())
    write_version(new)
    print(new)

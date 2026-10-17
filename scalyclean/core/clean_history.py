"""История быстрых очисток (локально, %APPDATA%)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_MAX = 12


@dataclass
class CleanRecord:
    when: str
    kind: str
    bytes_freed: int


def _store_path() -> Path:
    base = os.environ.get("APPDATA", "")
    if not base:
        base = str(Path.home())
    p = Path(base) / "ScalyCleaner" / "history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_history() -> list[CleanRecord]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        out: list[CleanRecord] = []
        for item in raw if isinstance(raw, list) else []:
            out.append(
                CleanRecord(
                    when=str(item.get("when", "")),
                    kind=str(item.get("kind", "quick")),
                    bytes_freed=int(item.get("bytes_freed", 0)),
                )
            )
        return out
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return []


def append_history(bytes_freed: int, kind: str = "quick") -> None:
    records = load_history()
    records.insert(
        0,
        CleanRecord(
            when=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            kind=kind,
            bytes_freed=max(0, int(bytes_freed)),
        ),
    )
    records = records[:_MAX]
    path = _store_path()
    path.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

"""Вытащить иконку из exe -> assets/custom.ico (если у тебя старый exe с правильной авой)."""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

import pefile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def largest_icon_blob(exe: Path) -> bytes:
    pe = pefile.PE(str(exe), fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    best = b""
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.struct.Id != 3:
            continue
        for e in entry.directory.entries:
            for e2 in e.directory.entries:
                off = e2.data.struct.OffsetToData
                size = e2.data.struct.Size
                blob = pe.get_data(off, size)
                if len(blob) > len(best):
                    best = blob
    return best


def main() -> None:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "ScalyCleaner.exe"
    if not exe.is_file():
        raise SystemExit(f"usage: extract_exe_icon.py <path\\to\\ScalyCleaner.exe>")
    blob = largest_icon_blob(exe)
    if len(blob) < 100:
        raise SystemExit("no icon in exe")
    ASSETS.mkdir(parents=True, exist_ok=True)
    try:
        im = Image.open(io.BytesIO(blob))
        im.save(ASSETS / "custom.ico", format="ICO")
        im.convert("RGBA").resize((512, 512), Image.Resampling.LANCZOS).save(
            ASSETS / "logo_source.png"
        )
    except Exception:
        (ASSETS / "custom.ico").write_bytes(blob)
    print(f"Wrote assets/custom.ico from {exe}")


if __name__ == "__main__":
    main()

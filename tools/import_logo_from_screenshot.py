"""One-off: crop icon from explorer screenshot -> assets/logo_source.png"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def crop_icon_from_explorer_shot(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    # нижняя полоса с именем файла
    body = im.crop((0, 0, w, max(1, h - 52)))
    bw, bh = body.size
    side = min(bw, bh)
    left = (bw - side) // 2
    top = 0
    if bh > side:
        top = (bh - side) // 4
    return body.crop((left, top, left + side, top + side))


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not src or not src.is_file():
        raise SystemExit("usage: import_logo_from_screenshot.py <screenshot.png>")
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = crop_icon_from_explorer_shot(src)
    out = ASSETS / "logo_source.png"
    icon.save(out)
    print(f"Wrote {out} ({icon.size[0]}x{icon.size[1]})")


if __name__ == "__main__":
    main()

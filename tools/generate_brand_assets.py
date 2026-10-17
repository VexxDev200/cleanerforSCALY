"""Генерация logo PNG + ICO для SCALY Cleaner."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(2, size // 16)
    d.ellipse(
        (pad, pad, size - pad, size - pad),
        fill="#0d9488",
        outline="#5eead4",
        width=max(1, size // 64),
    )
    inner = size // 5
    d.ellipse(
        (inner, inner, size - inner, size - inner),
        fill="#115e59",
    )
    font = _font(int(size * 0.52))
    text = "S"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        ((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1] - size // 32),
        text,
        fill="#ecfdf5",
        font=font,
    )
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes_png = (32, 48, 64, 128, 256)
    images: list[Image.Image] = []
    for s in sizes_png:
        im = draw_logo(s)
        im.save(ASSETS / f"logo_{s}.png")
        images.append(im)
    ico_sizes = [16, 32, 48, 64, 128, 256]
    master = draw_logo(256).convert("RGBA")
    master.save(
        ASSETS / "logo.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
    )
    draw_logo(512).save(ASSETS / "logo_512.png")
    print(f"Brand assets: {ASSETS}")


if __name__ == "__main__":
    main()

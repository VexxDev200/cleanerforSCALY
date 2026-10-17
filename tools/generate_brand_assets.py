"""Генерация logo PNG + ICO для SCALY Cleaner (из assets/logo_source.png или запасной S)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE_NAMES = ("logo_source.png", "logo.png", "brand.png", "icon.png")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_logo_fallback(size: int) -> Image.Image:
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


def load_master_logo() -> Image.Image:
    for name in SOURCE_NAMES:
        path = ASSETS / name
        if path.is_file():
            im = Image.open(path).convert("RGBA")
            side = min(im.size)
            if im.size[0] != im.size[1]:
                left = (im.size[0] - side) // 2
                top = (im.size[1] - side) // 2
                im = im.crop((left, top, left + side, top + side))
            if side < 256:
                im = im.resize((512, 512), Image.Resampling.LANCZOS)
            return im
    return draw_logo_fallback(512)


def logo_at_size(master: Image.Image, size: int) -> Image.Image:
    if master.size[0] == size:
        return master.copy()
    return master.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = load_master_logo()
    if master.size != (512, 512):
        master = master.resize((512, 512), Image.Resampling.LANCZOS)
    master.save(ASSETS / "logo_512.png")

    for s in (32, 48, 64, 128, 256):
        logo_at_size(master, s).save(ASSETS / f"logo_{s}.png")

    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_master = logo_at_size(master, 256)
    ico_master.save(
        ASSETS / "logo.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
    )
    src = next((ASSETS / n for n in SOURCE_NAMES if (ASSETS / n).is_file()), None)
    print(f"Brand assets: {ASSETS}" + (f" (from {src.name})" if src else " (fallback)"))


if __name__ == "__main__":
    main()

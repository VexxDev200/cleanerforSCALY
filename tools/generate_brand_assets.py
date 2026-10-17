"""Зелёная SCALY-иконка (октагон) для exe и UI. custom.ico — только если положишь сам."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

ICO_OVERRIDE = ("custom.ico", "app.ico", "scaly.ico")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arialbd.ttf", "arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _octagon_points(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    return [
        (
            cx + r * math.cos(math.pi / 8 + i * 2 * math.pi / 8),
            cy + r * math.sin(math.pi / 8 + i * 2 * math.pi / 8),
        )
        for i in range(8)
    ]


def draw_scaly_logo(size: int) -> Image.Image:
    """Зелёный октагон + круг + S — как в штатной сборке ScalyCleaner."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    r_outer = size * 0.47
    stroke = max(1, size // 48)
    d.polygon(
        _octagon_points(cx, cy, r_outer),
        fill="#0d9488",
        outline="#5eead4",
        width=stroke,
    )
    r_inner = size * 0.34
    d.ellipse(
        (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
        fill="#115e59",
        outline="#0f766e",
        width=max(1, stroke // 2),
    )
    font = _font(int(size * 0.46))
    text = "S"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        (cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1] - size * 0.02),
        text,
        fill="#ecfdf5",
        font=font,
    )
    return img


def logo_at_size(master: Image.Image, size: int) -> Image.Image:
    if master.size[0] == size:
        return master.copy()
    return master.resize((size, size), Image.Resampling.LANCZOS)


def write_png_set(master: Image.Image) -> None:
    master.save(ASSETS / "logo_512.png")
    for s in (32, 48, 64, 128, 256):
        logo_at_size(master, s).save(ASSETS / f"logo_{s}.png")


def write_ico_from_png(master: Image.Image) -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    frames = [logo_at_size(master, s).convert("RGBA") for s in sizes]
    frames[0].save(
        ASSETS / "logo.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )


def apply_user_ico() -> bool:
    for name in ICO_OVERRIDE:
        src = ASSETS / name
        if src.is_file() and src.stat().st_size > 500:
            shutil.copy2(src, ASSETS / "logo.ico")
            im = Image.open(src)
            im.load()
            best = im
            if getattr(im, "n_frames", 1) > 1:
                best_area = 0
                for i in range(im.n_frames):
                    im.seek(i)
                    frame = im.copy().convert("RGBA")
                    area = frame.size[0] * frame.size[1]
                    if area > best_area:
                        best_area = area
                        best = frame
            master = best.convert("RGBA").resize((512, 512), Image.Resampling.LANCZOS)
            write_png_set(master)
            print(f"Brand assets: exe icon from {name}")
            return True
    return False


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    if apply_user_ico():
        return
    master = draw_scaly_logo(512)
    write_png_set(master)
    write_ico_from_png(master)
    print("Brand assets: green Scaly octagon (default)")


if __name__ == "__main__":
    main()

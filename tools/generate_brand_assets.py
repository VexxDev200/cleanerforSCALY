"""PNG + ICO для exe/UI. Приоритет: assets/custom.ico → logo_source.png → запасная S."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

ICO_CANDIDATES = ("custom.ico", "app.ico", "scaly.ico", "logo.ico")
SOURCE_PNG = ("logo_source.png", "logo.png", "brand.png", "icon.png")


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
    d.ellipse((inner, inner, size - inner, size - inner), fill="#115e59")
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


def _key_out_dark_bg(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    corners = [im.getpixel((0, 0)), im.getpixel((w - 1, 0)), im.getpixel((0, h - 1))]
    bg = corners[0][:3]

    def near_bg(px: tuple) -> bool:
        return all(abs(px[i] - bg[i]) < 28 for i in range(3))

    px = im.load()
    for y in range(h):
        for x in range(w):
            if near_bg(px[x, y]):
                px[x, y] = (0, 0, 0, 0)
    box = im.getbbox()
    return im.crop(box) if box else im


def load_master_png() -> Image.Image | None:
    for name in SOURCE_PNG:
        path = ASSETS / name
        if not path.is_file():
            continue
        im = Image.open(path).convert("RGBA")
        if name == "logo_source.png" or im.size[0] < 400:
            im = _key_out_dark_bg(im)
        side = min(im.size)
        if im.size[0] != im.size[1]:
            left = (im.size[0] - side) // 2
            top = (im.size[1] - side) // 2
            im = im.crop((left, top, left + side, top + side))
        if side < 512:
            im = im.resize((512, 512), Image.Resampling.LANCZOS)
        elif side > 512:
            im = im.resize((512, 512), Image.Resampling.LANCZOS)
        return im
    return None


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


def copy_user_ico() -> Path | None:
    for name in ICO_CANDIDATES:
        src = ASSETS / name
        if not src.is_file() or src.stat().st_size < 500:
            continue
        if name != "logo.ico":
            shutil.copy2(src, ASSETS / "logo.ico")
        return src
    return None


def pngs_from_ico(ico_path: Path) -> Image.Image:
    im = Image.open(ico_path)
    im.load()
    if getattr(im, "n_frames", 1) > 1:
        best = im
        best_area = 0
        for i in range(im.n_frames):
            im.seek(i)
            frame = im.copy().convert("RGBA")
            area = frame.size[0] * frame.size[1]
            if area > best_area:
                best_area = area
                best = frame
        master = best.resize((512, 512), Image.Resampling.LANCZOS)
    else:
        master = im.convert("RGBA").resize((512, 512), Image.Resampling.LANCZOS)
    write_png_set(master)
    if ico_path.name != "logo.ico":
        shutil.copy2(ico_path, ASSETS / "logo.ico")
    return master


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    user_ico = copy_user_ico()
    if user_ico and user_ico.name in ("custom.ico", "app.ico", "scaly.ico"):
        pngs_from_ico(user_ico)
        print(f"Brand assets: {ASSETS} (exe icon from {user_ico.name})")
        return

    master = load_master_png()
    if master is None:
        master = draw_logo_fallback(512)
        print("Brand assets: fallback S (положи assets/logo_source.png или assets/custom.ico)")
    else:
        src = next(ASSETS / n for n in SOURCE_PNG if (ASSETS / n).is_file())
        print(f"Brand assets: from {src.name}")

    write_png_set(master)
    write_ico_from_png(master)


if __name__ == "__main__":
    main()

"""Логотип и иконка окна (dev + PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageTk


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    return _root() / "assets" / name


def apply_window_icon(window) -> None:
    path = asset_path("logo_64.png")
    if not path.is_file():
        path = asset_path("logo_48.png")
    if not path.is_file():
        return
    try:
        photo = ImageTk.PhotoImage(Image.open(path).convert("RGBA"))
        window.iconphoto(True, photo)
        window._scaly_icon = photo  # type: ignore[attr-defined]
    except Exception:
        pass


def load_logo_ctk(size: int = 40):
    from customtkinter import CTkImage

    path = asset_path(f"logo_{size}.png")
    if not path.is_file():
        path = asset_path("logo_64.png")
    if not path.is_file():
        return None
    return CTkImage(light_image=Image.open(path), dark_image=Image.open(path), size=(size, size))

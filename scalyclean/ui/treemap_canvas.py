"""Интерактивная treemap в стиле WizTree."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from scalyclean.core.utils import format_bytes

# Палитра как у WizTree (папки / типы)
_PALETTE = (
    "#4f7ec4",
    "#e06c88",
    "#56b881",
    "#e8a838",
    "#9b6dd7",
    "#3db8c5",
    "#d96fbf",
    "#7bc96f",
    "#c97a4a",
    "#6a8fd4",
    "#b85c5c",
    "#5cc4a8",
)


@dataclass
class TreemapCell:
    label: str
    size: int
    path: str
    color: str
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0


def _color_for_index(i: int) -> str:
    return _PALETTE[i % len(_PALETTE)]


def _layout_slice_dice(
    items: list[tuple[float, TreemapCell]],
    x: float,
    y: float,
    w: float,
    h: float,
) -> list[TreemapCell]:
    """Надёжная разбивка: у каждого элемента свой прямоугольник."""
    if not items or w < 1 or h < 1:
        return []
    total = sum(v for v, _ in items)
    if total <= 0:
        return []

    out: list[TreemapCell] = []

    def rec(chunk: list[tuple[float, TreemapCell]], rx: float, ry: float, rw: float, rh: float) -> None:
        if not chunk:
            return
        if len(chunk) == 1:
            cell = chunk[0][1]
            cell.x, cell.y, cell.w, cell.h = rx, ry, rw, rh
            out.append(cell)
            return
        s = sum(v for v, _ in chunk)
        if s <= 0:
            return
        mid = max(1, len(chunk) // 2)
        left = chunk[:mid]
        right = chunk[mid:]
        sl = sum(v for v, _ in left)
        if rw >= rh:
            lw = rw * (sl / s)
            rec(left, rx, ry, lw, rh)
            rec(right, rx + lw, ry, rw - lw, rh)
        else:
            lh = rh * (sl / s)
            rec(left, rx, ry, rw, lh)
            rec(right, rx, ry + lh, rw, rh - lh)

    rec(items, x, y, w, h)
    return out


class TreemapCanvas(tk.Canvas):
    def __init__(self, master, on_activate: Callable[[TreemapCell], None] | None = None, **kwargs) -> None:
        super().__init__(master, highlightthickness=0, **kwargs)
        self._cells: list[TreemapCell] = []
        self._on_activate = on_activate
        self._hover: TreemapCell | None = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._dblclick)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._clear_hover())

    def set_cells(self, cells: list[TreemapCell]) -> None:
        sorted_cells = sorted(cells, key=lambda c: c.size, reverse=True)
        for i, c in enumerate(sorted_cells):
            if not c.color:
                c.color = _color_for_index(i)
        self._cells = sorted_cells
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 20)
        h = max(self.winfo_height(), 20)
        if not self._cells:
            self.create_text(
                w / 2,
                h / 2,
                text="Запусти «Анализ» — карта как в WizTree\n(клик по блоку = войти в папку)",
                fill="#888",
                font=("Segoe UI", 11),
                justify="center",
            )
            return

        items = [(float(max(1, c.size)), c) for c in self._cells]
        laid = _layout_slice_dice(items, 1, 1, w - 2, h - 2)
        self._drawn = laid
        for cell in laid:
            if cell.w < 2 or cell.h < 2:
                continue
            self.create_rectangle(
                cell.x,
                cell.y,
                cell.x + cell.w,
                cell.y + cell.h,
                fill=cell.color,
                outline="#101010",
                width=1,
                tags=("cell", cell.path),
            )
            if cell.w > 36 and cell.h > 22:
                name = cell.label if len(cell.label) <= 28 else cell.label[:26] + "…"
                pct = ""
                total = sum(c.size for c in self._cells)
                if total > 0:
                    pct = f" ({100.0 * cell.size / total:.1f}%)"
                self.create_text(
                    cell.x + cell.w / 2,
                    cell.y + cell.h / 2,
                    text=f"{name}\n{format_bytes(cell.size)}{pct}",
                    fill="#ffffff",
                    font=("Segoe UI", 9, "bold"),
                    width=max(30, cell.w - 6),
                    justify="center",
                )

    def _cell_at(self, x: int, y: int) -> TreemapCell | None:
        for cell in reversed(getattr(self, "_drawn", self._cells)):
            if cell.x <= x <= cell.x + cell.w and cell.y <= y <= cell.y + cell.h:
                return cell
        return None

    def _click(self, event) -> None:
        cell = self._cell_at(event.x, event.y)
        if cell and self._on_activate:
            self._on_activate(cell)

    def _dblclick(self, event) -> None:
        self._click(event)

    def _motion(self, event) -> None:
        cell = self._cell_at(event.x, event.y)
        if cell != self._hover:
            self._hover = cell
            self.config(cursor="hand2" if cell else "")

    def _clear_hover(self) -> None:
        self._hover = None
        self.config(cursor="")

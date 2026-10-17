"""Вкладка «Главная»: оценка ПК, быстрая очистка, история."""

from __future__ import annotations

import customtkinter as ctk

from scalyclean import __version__
from scalyclean.core.branding import load_logo_ctk
from scalyclean.core.clean_history import load_history
from scalyclean.core.utils import format_bytes


def _health_score(ram_pct: float, disk_pct: float, cache_mb: float) -> int:
    score = 100
    if ram_pct > 85:
        score -= 25
    elif ram_pct > 70:
        score -= 12
    if disk_pct > 90:
        score -= 25
    elif disk_pct > 80:
        score -= 10
    if cache_mb > 4096:
        score -= 15
    elif cache_mb > 2048:
        score -= 8
    return max(0, min(100, score))


class HomePanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_quick_clean,
        on_refresh_stats,
        on_log,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_quick_clean = on_quick_clean
        self._on_refresh_stats = on_refresh_stats
        self._on_log = on_log

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 8))
        logo = load_logo_ctk(72)
        if logo:
            ctk.CTkLabel(top, text="", image=logo).pack(side="left", padx=(0, 16))
        col = ctk.CTkFrame(top, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            col,
            text="Добро пожаловать",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            col,
            text=f"SCALY Cleaner v{__version__} — бережная очистка без закрытия игр",
            text_color="#9aa0a6",
        ).pack(anchor="w")

        cards = ctk.CTkFrame(self)
        cards.pack(fill="x", padx=12, pady=8)
        self._score_label = ctk.CTkLabel(
            cards,
            text="Состояние ПК: …",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self._score_label.pack(padx=16, pady=(14, 4), anchor="w")
        self._hint_label = ctk.CTkLabel(cards, text="", justify="left", text_color="#9aa0a6")
        self._hint_label.pack(padx=16, pady=(0, 12), anchor="w")

        ctk.CTkButton(
            self,
            text="Быстрая очистка (RAM + GPU + диск)",
            height=52,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#0d9488",
            hover_color="#0f766e",
            command=self._on_quick_clean,
        ).pack(fill="x", padx=12, pady=8)

        hist_frame = ctk.CTkFrame(self)
        hist_frame.pack(fill="both", expand=True, padx=12, pady=8)
        ctk.CTkLabel(hist_frame, text="Недавние очистки", anchor="w").pack(
            fill="x", padx=12, pady=(10, 4)
        )
        self._history = ctk.CTkTextbox(hist_frame, height=140)
        self._history.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.refresh_display(ram_pct=0, disk_pct=0, cache_bytes=0)

    def refresh_display(self, ram_pct: float, disk_pct: float, cache_bytes: int) -> None:
        cache_mb = cache_bytes / (1024 * 1024)
        score = _health_score(ram_pct, disk_pct, cache_mb)
        color = "#4ade80" if score >= 75 else "#fbbf24" if score >= 50 else "#f87171"
        self._score_label.configure(text=f"Состояние ПК: {score}/100", text_color=color)
        tips: list[str] = []
        if ram_pct > 75:
            tips.append("RAM загружена — быстрая очистка поможет")
        if disk_pct > 85:
            tips.append("мало места на диске — загляни в «Анализ»")
        if cache_mb > 2048:
            tips.append("крупные GPU-кэши — можно почистить VRAM")
        if not tips:
            tips.append("всё в норме — можно профилактику одной кнопкой")
        self._hint_label.configure(text=" · ".join(tips))

        lines = []
        for rec in load_history():
            lines.append(f"{rec.when}  +{format_bytes(rec.bytes_freed)}  ({rec.kind})")
        if not lines:
            lines.append("Пока пусто — нажми «Быстрая очистка»")
        self._history.delete("0.0", "end")
        self._history.insert("0.0", "\n".join(lines))

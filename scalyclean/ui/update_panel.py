"""Вкладка: проверка обновлений."""

from __future__ import annotations

import os
import threading
from tkinter import messagebox

import customtkinter as ctk

from scalyclean import __version__
from scalyclean.core.branding import load_logo_ctk
from scalyclean.core.updater import (
    check_for_update,
    diagnose_update,
    effective_local_version,
    version_gt,
)


class UpdatePanel(ctk.CTkFrame):
    def __init__(self, master, on_log, on_status, on_update_offered) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_log = on_log
        self._on_status = on_status
        self._on_update_offered = on_update_offered

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=8, pady=(8, 4))
        logo = load_logo_ctk(56)
        if logo:
            ctk.CTkLabel(head, text="", image=logo).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            head,
            text="SCALY Cleaner — обновления",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")

        ctk.CTkLabel(
            self,
            text="Проверка GitHub ~1 мин · вкладка «Обновления» · возврат в окно. (тест v1.0.12)",
            justify="left",
            text_color="#9aa0a6",
        ).pack(anchor="w", padx=12, pady=8)

        info = ctk.CTkFrame(self)
        info.pack(fill="x", padx=12, pady=8)
        self._ver_label = ctk.CTkLabel(info, text=f"Твоя версия: v{__version__}", anchor="w")
        self._ver_label.pack(fill="x", padx=12, pady=6)
        self._server_label = ctk.CTkLabel(info, text="На сервере: …", anchor="w")
        self._server_label.pack(fill="x", padx=12, pady=6)
        self._result_label = ctk.CTkLabel(info, text="Нажми «Проверить сейчас»", anchor="w")
        self._result_label.pack(fill="x", padx=12, pady=6)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=12)
        ctk.CTkButton(row, text="Проверить сейчас", width=160, command=self.run_check).pack(
            side="left", padx=4
        )
        ctk.CTkButton(
            row,
            text="Тест: как v1.0.0",
            width=140,
            fg_color="#334155",
            command=self.run_test_old_client,
        ).pack(side="left", padx=4)

        self._refresh_labels()

    def _refresh_labels(self) -> None:
        local = effective_local_version()
        extra = ""
        if local != __version__:
            extra = f" (тест v{local})"
        self._ver_label.configure(text=f"Твоя версия: v{__version__}{extra}")

    def run_check(self) -> None:
        self._on_status("Проверка обновлений…")

        def work() -> None:
            diag = diagnose_update()
            info = check_for_update()
            self.after(0, lambda: self._show(diag, info))

        threading.Thread(target=work, daemon=True).start()

    def run_test_old_client(self) -> None:
        os.environ["SCALY_UPDATE_TEST_VERSION"] = "1.0.0"
        self._refresh_labels()
        self._on_log("[Обновление] Тест: клиент v1.0.0")
        self.run_check()

    def _show(self, diag, info) -> None:
        self._refresh_labels()
        self._server_label.configure(text=f"На сервере: v{diag.remote_version or '—'}")
        for line in diag.public_summary_lines(include_debug=True):
            self._on_log(f"[Обновление] {line}")
        public = "\n".join(diag.public_summary_lines(include_debug=False))
        newer_on_server = bool(
            diag.remote_version
            and version_gt(diag.remote_version, effective_local_version())
        )
        if diag.update_available and info:
            self._result_label.configure(
                text=f"Доступно v{info.version}",
                text_color="#4ade80",
            )
            self._on_update_offered(info)
            messagebox.showinfo("Обновление", public)
        elif info and newer_on_server:
            self._result_label.configure(
                text=f"Доступно v{info.version}",
                text_color="#4ade80",
            )
            self._on_update_offered(info)
            messagebox.showinfo("Обновление", public)
        elif newer_on_server:
            self._result_label.configure(
                text=f"На сервере v{diag.remote_version}",
                text_color="#fbbf24",
            )
            extra = "\n\n" + "\n".join(diag.errors) if diag.errors else ""
            messagebox.showwarning("Обновление", public + extra)
        elif diag.errors:
            self._result_label.configure(text="Ошибка проверки", text_color="#f87171")
            messagebox.showwarning(
                "Обновление",
                public + "\n\n" + "\n".join(diag.errors),
            )
        else:
            self._result_label.configure(text="Последняя версия", text_color="#9aa0a6")
            messagebox.showinfo("Обновление", public)
        self._on_status("Готово")

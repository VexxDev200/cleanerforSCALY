import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import psutil

from scalyclean import __version__
from scalyclean.core.admin import is_admin
from scalyclean.core.updater import (
    UPDATE_MIN_GAP_SEC,
    UPDATE_POLL_MS,
    check_for_update,
    diagnose_update,
    install_update,
    is_frozen_app,
)
from scalyclean.core.utils import format_bytes
from scalyclean.modules.disk_analyzer import target_matches_drive
from scalyclean.modules.disk_cleaner import clean_targets, scan_all
from scalyclean.modules.disk_targets import all_disk_targets, targets_for_drive
from scalyclean.modules.volumes import default_drive
from scalyclean.core.branding import apply_window_icon, load_logo_ctk
from scalyclean.core.clean_history import append_history
from scalyclean.ui.analyzer_panel import AnalyzerPanel
from scalyclean.ui.games_panel import GamesPanel
from scalyclean.ui.home_panel import HomePanel
from scalyclean.ui.update_panel import UpdatePanel
from scalyclean.modules.ram_cleaner import clean_ram, get_ram_stats
from scalyclean.modules.system_cleaner import clean_old_windows_logs, start_dism_component_cleanup
from scalyclean.modules.vram_cleaner import clean_vram_caches, flush_dwm, inspect_vram


class ScalyCleanerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("SCALY Cleaner — анализ диска · очистка · RAM · VRAM")
        self.geometry("1320x960")
        self.minsize(1000, 720)

        self._disk_vars: dict[str, tk.BooleanVar] = {}
        self._disk_rows: dict[str, ctk.CTkFrame] = {}
        self._current_drive = default_drive()
        self._busy = False
        self._gentle_var = tk.BooleanVar(value=True)
        self._pending_update = None
        self._update_progress_win: ctk.CTkToplevel | None = None
        self._last_update_check = 0.0

        self._build_header()
        self._build_stats_row()
        self._build_tabs()
        self._build_log()
        self._build_footer()

        apply_window_icon(self)
        self.bind("<FocusIn>", self._on_app_focus)
        self.after(200, self._boot_refresh)
        self._schedule_update_poll()

    def _boot_refresh(self) -> None:
        self._on_drive_changed(self._analyzer.get_selected_drive())
        self.refresh_stats()
        if self._should_check_updates():
            self._request_update_check(force=True)
            self.after(15_000, lambda: self._request_update_check(force=True))

    def _build_header(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))
        title_row = ctk.CTkFrame(top, fg_color="transparent")
        title_row.pack(side="left")
        logo = load_logo_ctk(40)
        if logo:
            ctk.CTkLabel(title_row, text="", image=logo).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            title_row,
            text="SCALY Cleaner",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            title_row,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=12),
            text_color="#9aa0a6",
        ).pack(side="left", padx=(10, 0))
        self._update_btn = ctk.CTkButton(
            title_row,
            text="Обновить",
            width=120,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._start_app_update,
        )
        admin_txt = "Админ: да" if is_admin() else "Админ: нет (часть функций ограничена)"
        self._admin_label = ctk.CTkLabel(top, text=admin_txt, text_color="#9aa0a6")
        self._admin_label.pack(side="right")

    def _build_stats_row(self) -> None:
        row = ctk.CTkFrame(self)
        row.pack(fill="x", padx=16, pady=8)

        self._ram_label = ctk.CTkLabel(row, text="RAM: …", font=ctk.CTkFont(size=13))
        self._ram_label.pack(side="left", padx=12, pady=10)

        self._disk_label = ctk.CTkLabel(row, text="Диск C: …", font=ctk.CTkFont(size=13))
        self._disk_label.pack(side="left", padx=12, pady=10)

        self._vram_label = ctk.CTkLabel(row, text="GPU кэши: …", font=ctk.CTkFont(size=13))
        self._vram_label.pack(side="left", padx=12, pady=10)

        ctk.CTkCheckBox(
            row,
            text="Бережный режим (не трогать игры и лаунчеры)",
            variable=self._gentle_var,
        ).pack(side="right", padx=8)
        ctk.CTkButton(
            row,
            text="Проверить обновления",
            width=150,
            command=self._manual_update_check,
        ).pack(side="right", padx=6)
        ctk.CTkButton(row, text="Статус", width=88, command=self.refresh_stats).pack(
            side="right", padx=12
        )

    def _build_tabs(self) -> None:
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=16, pady=4)

        tab_home = self._tabs.add("Главная")
        tab_analyze = self._tabs.add("Анализ")
        tab_games = self._tabs.add("Игры")
        tab_disk = self._tabs.add("Очистка")
        tab_ram = self._tabs.add("RAM")
        tab_vram = self._tabs.add("VRAM / GPU")
        tab_all = self._tabs.add("Всё сразу")
        tab_updates = self._tabs.add("Обновления")

        self._home = HomePanel(
            tab_home,
            on_quick_clean=self.run_quick_clean,
            on_refresh_stats=self.refresh_stats,
            on_log=self.log,
        )
        self._home.pack(fill="both", expand=True, padx=4, pady=4)

        self._analyzer = AnalyzerPanel(
            tab_analyze,
            on_drive_change=self._on_drive_changed,
            on_status=lambda t: self._status.configure(text=t),
        )
        self._analyzer.pack(fill="both", expand=True, padx=4, pady=4)

        self._games = GamesPanel(
            tab_games,
            on_status=lambda t: self._status.configure(text=t),
            on_log=self.log,
        )
        self._games.pack(fill="both", expand=True, padx=4, pady=4)

        self._tabs.set("Главная")

        self._build_disk_tab(tab_disk)
        self._build_ram_tab(tab_ram)
        self._build_vram_tab(tab_vram)
        self._build_all_tab(tab_all)

        self._updates = UpdatePanel(
            tab_updates,
            on_log=self.log,
            on_status=lambda t: self._status.configure(text=t),
            on_update_offered=self._offer_update,
        )
        self._updates.pack(fill="both", expand=True, padx=4, pady=4)
        self._tabs.configure(command=self._on_tab_changed)

    def _on_tab_changed(self) -> None:
        if self._tabs.get() == "Обновления":
            self._request_update_check(force=True)
        if self._tabs.get() == "Главная":
            self.refresh_stats()

    def _request_update_check(self, force: bool = False) -> None:
        if not self._should_check_updates() or self._busy:
            return
        now = time.time()
        if not force and now - self._last_update_check < UPDATE_MIN_GAP_SEC:
            return
        self._last_update_check = now
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _schedule_update_poll(self) -> None:
        if not is_frozen_app():
            return
        self.after(UPDATE_POLL_MS, self._poll_updates)

    def _poll_updates(self) -> None:
        self._request_update_check()
        self._schedule_update_poll()

    def _on_app_focus(self, _event) -> None:
        if is_frozen_app():
            self._request_update_check()

    def _should_check_updates(self) -> bool:
        if is_frozen_app():
            return True
        flag = os.environ.get("SCALY_FORCE_UPDATE_CHECK", "").strip().lower()
        return flag in ("1", "true", "yes", "on")

    def _check_updates_worker(self) -> None:
        info = check_for_update()
        if info:
            self.after(0, lambda: self._offer_update(info))

    def _manual_update_check(self) -> None:
        if self._busy:
            messagebox.showwarning("SCALY Cleaner", "Дождись окончания текущей операции.")
            return
        self._status.configure(text="Проверка обновлений…")

        def work() -> None:
            diag = diagnose_update()
            info = check_for_update()
            self.after(0, lambda: self._show_update_diagnosis(diag, info))

        threading.Thread(target=work, daemon=True).start()

    def _show_update_diagnosis(self, diag, info) -> None:
        for line in diag.public_summary_lines(include_debug=True):
            self.log(f"[Обновление] {line}")
        text = "\n".join(diag.public_summary_lines(include_debug=False))
        if info:
            self._offer_update(info)
            messagebox.showinfo("Обновления", text + "\n\nНажми «Обновить» в шапке.")
        elif diag.errors:
            messagebox.showwarning(
                "Обновления",
                text + "\n\n" + "\n".join(diag.errors),
            )
        else:
            messagebox.showinfo("Обновления", text)
        self._status.configure(text="Готово")

    def _offer_update(self, info) -> None:
        self._pending_update = info
        self._update_btn.pack(side="left", padx=(12, 0))
        short = info.notes[:120] + ("…" if len(info.notes) > 120 else "")
        self.log(f"[Обновление] Доступна v{info.version}. {short}")
        self._status.configure(text=f"Доступно обновление v{info.version} — нажми «Обновить»")

    def _start_app_update(self) -> None:
        if not self._pending_update:
            threading.Thread(target=self._check_updates_worker, daemon=True).start()
            return
        if self._busy:
            messagebox.showwarning("SCALY Cleaner", "Дождись окончания текущей операции.")
            return
        if not messagebox.askyesno(
            "Обновление",
            f"Скачать v{self._pending_update.version} и перезапустить программу?\n\n"
            f"{self._pending_update.notes or '—'}",
        ):
            return
        self.set_busy(True, "Скачивание обновления…")
        self._open_update_progress()
        info = self._pending_update

        def work() -> None:
            err: str | None = None
            try:

                def prog(done: int, total: int | None) -> None:
                    self.after(0, lambda: self._update_progress_set(done, total))

                install_update(info, on_progress=prog)
            except Exception as e:
                err = str(e)
            if err:
                self.after(0, lambda: self._finish_update_failed(err))

        threading.Thread(target=work, daemon=True).start()

    def _open_update_progress(self) -> None:
        if self._update_progress_win and self._update_progress_win.winfo_exists():
            return
        win = ctk.CTkToplevel(self)
        win.title("Обновление")
        win.geometry("420x120")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Скачивание новой версии…").pack(pady=(16, 8))
        self._update_prog = ctk.CTkProgressBar(win, width=360)
        self._update_prog.pack(pady=8)
        self._update_prog.set(0)
        self._update_prog_label = ctk.CTkLabel(win, text="0 %")
        self._update_prog_label.pack()
        self._update_progress_win = win

    def _update_progress_set(self, done: int, total: int | None) -> None:
        if total and total > 0:
            p = min(1.0, done / total)
            self._update_prog.set(p)
            self._update_prog_label.configure(text=f"{int(p * 100)} % · {format_bytes(done)}")
        else:
            self._update_prog.set(0.5)
            self._update_prog_label.configure(text=f"Загрузка… {format_bytes(done)}")

    def _finish_update_failed(self, err: str) -> None:
        self.set_busy(False, "Ошибка обновления")
        if self._update_progress_win and self._update_progress_win.winfo_exists():
            self._update_progress_win.destroy()
        self._update_progress_win = None
        messagebox.showerror("Обновление", err)
        self.log(f"[Обновление] Ошибка: {err}")

    def _build_disk_tab(self, parent: ctk.CTkFrame) -> None:
        hint = ctk.CTkFrame(parent, fg_color="transparent")
        hint.pack(fill="x", padx=4, pady=(4, 0))
        self._clean_drive_label = ctk.CTkLabel(
            hint,
            text="",
            text_color="#9aa0a6",
            justify="left",
        )
        self._clean_drive_label.pack(anchor="w")
        self._update_clean_drive_hint()

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(4, 8))
        ctk.CTkButton(toolbar, text="Сканировать", command=self.scan_disk).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="Выбрать всё", command=self.select_all_disk).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="Снять всё", command=self.select_none_disk).pack(side="left", padx=4)
        ctk.CTkButton(toolbar, text="Очистить выбранное", fg_color="#1a7f37", command=self.run_disk_clean).pack(
            side="right", padx=4
        )

        self._disk_scroll = ctk.CTkScrollableFrame(parent)
        self._disk_scroll.pack(fill="both", expand=True)

        for t in all_disk_targets():
            # По умолчанию: только безопасные кэши/temp (без админ-путей и risky)
            var = tk.BooleanVar(value=not t.risky and not t.needs_admin)
            self._disk_vars[t.id] = var
            row = ctk.CTkFrame(self._disk_scroll, fg_color="transparent")
            self._disk_rows[t.id] = row
            suffix = " ⚠" if t.risky else (" 🔒" if t.needs_admin else "")
            ctk.CTkCheckBox(row, text=f"{t.label}{suffix}", variable=var, width=420).pack(
                side="left", padx=4
            )
            lbl = ctk.CTkLabel(row, text="—", width=120, anchor="e")
            lbl.pack(side="right", padx=8)
            setattr(self, f"_disk_size_{t.id}", lbl)

        self._disk_total_label = ctk.CTkLabel(parent, text="Итого к очистке: —")
        self._disk_total_label.pack(pady=8)
        self._filter_disk_targets()

    def _build_ram_tab(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Бережный: только мягкий standby + процессы без игр/Steam.\n"
            "Сними галочку «Бережный режим» в шапке для жёсткой очистки (игры могут вылететь).",
            justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        ctk.CTkButton(
            parent,
            text="Очистить RAM",
            height=40,
            fg_color="#1a7f37",
            command=self.run_ram_clean,
        ).pack(pady=12)

    def _build_vram_tab(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Чистим только свободные shader-кэши. Занятые GPU-файлы пропускаем — игра не закрывается.\n"
            "Для максимума — закрой игру сам и сними «Бережный режим».",
            justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        self._gpu_info = ctk.CTkTextbox(parent, height=180)
        self._gpu_info.pack(fill="both", expand=True, padx=8, pady=4)
        ctk.CTkButton(
            parent,
            text="Очистить GPU кэши + DwmFlush",
            height=40,
            fg_color="#1a7f37",
            command=self.run_vram_clean,
        ).pack(pady=12)

    def _build_all_tab(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Полный цикл: RAM → GPU кэши → все безопасные цели на диске → логи (если админ).\n"
            "Опционально: DISM Component Cleanup (долго, в фоне).",
            justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        self._dism_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(parent, text="Запустить DISM /StartComponentCleanup (WinSxS)", variable=self._dism_var).pack(
            anchor="w", padx=12
        )
        ctk.CTkButton(
            parent,
            text="🧹 ПОЛНАЯ ОЧИСТКА",
            height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#b45309",
            hover_color="#92400e",
            command=self.run_full_clean,
        ).pack(pady=24)

    def _build_log(self) -> None:
        ctk.CTkLabel(self, text="Журнал", anchor="w").pack(fill="x", padx=18)
        self._log = ctk.CTkTextbox(self, height=100)
        self._log.pack(fill="x", padx=16, pady=(0, 8))

    def _build_footer(self) -> None:
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 12))
        self._status = ctk.CTkLabel(foot, text="Готов")
        self._status.pack(side="left")

    def log(self, msg: str) -> None:
        self._log.insert("end", msg + "\n")
        self._log.see("end")

    def set_busy(self, busy: bool, status: str = "") -> None:
        self._busy = busy
        if status:
            self._status.configure(text=status)

    def _on_drive_changed(self, drive: str) -> None:
        self._current_drive = drive
        self._filter_disk_targets()
        self._update_clean_drive_hint()
        self.refresh_stats()

    def _update_clean_drive_hint(self) -> None:
        d = self._current_drive.rstrip("\\")
        n = len(targets_for_drive(self._current_drive))
        self._clean_drive_label.configure(
            text=f"Том {d}: показаны только безопасные цели очистки на этом диске ({n} пунктов). "
            "Полный обзор — вкладка «Анализ диска»."
        )

    def _filter_disk_targets(self) -> None:
        for t in all_disk_targets():
            row = self._disk_rows.get(t.id)
            if not row:
                continue
            show = t.mode == "recycle" or target_matches_drive(t.path, self._current_drive)
            if show:
                row.pack(fill="x", pady=2)
            else:
                row.pack_forget()

    def refresh_stats(self) -> None:
        ram = get_ram_stats()
        self._ram_label.configure(
            text=f"RAM: {format_bytes(ram.used)} / {format_bytes(ram.total)} ({ram.percent:.0f}%)"
        )
        drive = self._current_drive
        try:
            du = psutil.disk_usage(drive)
            letter = drive.rstrip("\\")
            self._disk_label.configure(
                text=f"{letter}: свободно {format_bytes(du.free)} / {format_bytes(du.total)} ({du.percent:.0f}% занято)"
            )
        except OSError:
            self._disk_label.configure(text=f"{drive}: n/a")
        vr = inspect_vram()
        names = ", ".join(a.name for a in vr.adapters[:2]) or "GPU"
        self._vram_label.configure(text=f"GPU кэши: {format_bytes(vr.cache_size)} · {names}")
        self._refresh_gpu_text(vr)
        if hasattr(self, "_home"):
            disk_pct = 0.0
            try:
                disk_pct = float(psutil.disk_usage(drive).percent)
            except OSError:
                pass
            self._home.refresh_display(ram.percent, disk_pct, vr.cache_size)

    def _refresh_gpu_text(self, vr) -> None:
        lines = ["=== Адаптеры ==="]
        for a in vr.adapters:
            ram = f"{a.adapter_ram_mb} MB" if a.adapter_ram_mb else "?"
            lines.append(f"  • {a.name} ({ram})")
        lines.append("")
        lines.append("=== Тяжёлые процессы (WS) ===")
        for pid, name, mb in vr.gpu_processes[:15]:
            lines.append(f"  {pid:6}  {name:24}  {mb} MB")
        self._gpu_info.delete("0.0", "end")
        self._gpu_info.insert("0.0", "\n".join(lines))

    def select_all_disk(self) -> None:
        for v in self._disk_vars.values():
            v.set(True)

    def select_none_disk(self) -> None:
        for v in self._disk_vars.values():
            v.set(False)

    def _selected_disk_ids(self) -> set[str]:
        allowed = {t.id for t in targets_for_drive(self._current_drive)}
        return {tid for tid, var in self._disk_vars.items() if var.get() and tid in allowed}

    def scan_disk(self) -> None:
        if self._busy:
            return
        self.set_busy(True, "Сканирование диска…")

        def work() -> None:
            sizes = scan_all(self._selected_disk_ids())
            total = sum(sizes.values())
            self.after(0, lambda: self._apply_scan(sizes, total))

        threading.Thread(target=work, daemon=True).start()

    def _apply_scan(self, sizes: dict[str, int], total: int) -> None:
        for tid, size in sizes.items():
            lbl = getattr(self, f"_disk_size_{tid}", None)
            if lbl:
                lbl.configure(text=format_bytes(size))
        self._disk_total_label.configure(text=f"Итого к очистке: {format_bytes(total)}")
        self.set_busy(False, "Готов")
        self.log(f"Скан диска: {format_bytes(total)} в выбранных категориях")

    def run_disk_clean(self) -> None:
        if self._busy:
            return
        ids = self._selected_disk_ids()
        if not ids:
            messagebox.showwarning("SCALY", "Ничего не выбрано")
            return
        self.set_busy(True, "Очистка диска…")

        def work() -> None:
            results = clean_targets(ids, admin=is_admin())
            freed = sum(r.bytes_freed for r in results)
            self.after(0, lambda: self._finish_disk(results, freed))

        threading.Thread(target=work, daemon=True).start()

    def _finish_disk(self, results, freed: int) -> None:
        for r in results:
            if r.bytes_freed or r.errors:
                self.log(f"[Диск] {r.name}: +{format_bytes(r.bytes_freed)}, файлов {r.files_removed}")
                for e in r.errors[:3]:
                    self.log(f"    ! {e}")
        self.set_busy(False, "Готов")
        self.log(f"Диск: освобождено ~{format_bytes(freed)}")
        self.refresh_stats()
        self.scan_disk()

    def run_quick_clean(self) -> None:
        if self._busy:
            return
        self.set_busy(True, "Быстрая очистка…")
        gentle = self._gentle_var.get()

        def work() -> None:
            rep = clean_ram(gentle=gentle)
            ram_delta = max(0, rep.after.available - rep.before.available)
            vram = clean_vram_caches(gentle=gentle)
            flush_dwm()
            safe_ids = {t.id for t in targets_for_drive(self._current_drive) if not t.risky}
            disk = clean_targets(safe_ids, admin=is_admin())
            disk_freed = sum(r.bytes_freed for r in disk)
            total = ram_delta + vram.bytes_freed + disk_freed
            append_history(total, "quick")
            self.after(0, lambda: self._finish_quick(rep, vram, disk_freed, total))

        threading.Thread(target=work, daemon=True).start()

    def _finish_quick(self, rep, vram, disk_freed: int, total: int) -> None:
        self._finish_ram(rep)
        self.log(f"[Быстро] GPU +{format_bytes(vram.bytes_freed)}, диск +{format_bytes(disk_freed)}")
        self.log(f"[Быстро] всего ~{format_bytes(total)}")
        self.set_busy(False, "Готово")
        self.refresh_stats()

    def run_ram_clean(self) -> None:
        if self._busy:
            return
        self.set_busy(True, "RAM…")

        def work() -> None:
            rep = clean_ram(gentle=self._gentle_var.get())
            self.after(0, lambda: self._finish_ram(rep))

        threading.Thread(target=work, daemon=True).start()

    def _finish_ram(self, rep) -> None:
        delta = rep.after.available - rep.before.available
        self.log(
            f"[RAM] доступно: {format_bytes(rep.before.available)} → {format_bytes(rep.after.available)} "
            f"(+{format_bytes(max(0, delta))})"
        )
        self.log(f"  standby={rep.standby_purged} WS={rep.working_sets_emptied} trimmed={rep.processes_trimmed}")
        for e in rep.errors:
            self.log(f"  ! {e}")
        self.set_busy(False, "Готов")
        self.refresh_stats()

    def run_vram_clean(self) -> None:
        if self._busy:
            return
        self.set_busy(True, "VRAM кэши…")

        def work() -> None:
            cr = clean_vram_caches(gentle=self._gentle_var.get())
            dwm_err = flush_dwm()
            self.after(0, lambda: self._finish_vram(cr, dwm_err))

        threading.Thread(target=work, daemon=True).start()

    def _finish_vram(self, cr, dwm_err) -> None:
        self.log(f"[VRAM] {cr.name}: +{format_bytes(cr.bytes_freed)}, файлов {cr.files_removed}")
        for e in cr.errors:
            self.log(f"  {e}")
        for e in dwm_err:
            self.log(f"  Dwm: {e}")
        self.set_busy(False, "Готов")
        self.refresh_stats()

    def run_full_clean(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno("SCALY", "Запустить полную очистку?"):
            return
        self.set_busy(True, "Полная очистка…")

        def work() -> None:
            gentle = self._gentle_var.get()
            rep = clean_ram(gentle=gentle)
            vram = clean_vram_caches(gentle=gentle)
            flush_dwm()
            safe_ids = {
                t.id
                for t in targets_for_drive(self._current_drive)
                if not t.risky
            }
            disk = clean_targets(safe_ids, admin=is_admin())
            logs = clean_old_windows_logs(is_admin())
            dism = False
            dism_err: list[str] = []
            if self._dism_var.get() and is_admin():
                dism, dism_err = start_dism_component_cleanup()
            self.after(
                0,
                lambda: self._finish_full(rep, vram, disk, logs, dism, dism_err),
            )

        threading.Thread(target=work, daemon=True).start()

    def _finish_full(self, rep, vram, disk_results, logs, dism, dism_err) -> None:
        self._finish_ram(rep)
        self.log(f"[VRAM] +{format_bytes(vram.bytes_freed)}")
        total_disk = sum(r.bytes_freed for r in disk_results)
        self.log(f"[Диск] безопасные категории: +{format_bytes(total_disk)}")
        self.log(f"[Логи] +{format_bytes(logs.bytes_freed)}")
        if dism:
            self.log("[DISM] Component Cleanup запущен в фоне (может занять десятки минут)")
        for e in dism_err:
            self.log(f"  DISM: {e}")
        self.set_busy(False, "Готово")
        self.refresh_stats()


def run_app() -> None:
    app = ScalyCleanerApp()
    app.mainloop()

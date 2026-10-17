import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from scalyclean.core.admin import is_admin
from scalyclean.core.utils import format_bytes
from scalyclean.core.win_delete import force_delete_tree, try_close_steam
from scalyclean.modules.games_scanner import (
    GameItem,
    LauncherCache,
    discover_games,
    discover_launcher_caches,
    is_safe_game_delete_path,
    measure_cache,
    measure_game,
)


def _size_text(item: GameItem | LauncherCache) -> str:
    if item.size > 0:
        return format_bytes(item.size)
    return "…"


class GamesPanel(ctk.CTkFrame):
    def __init__(self, master, on_status=None, on_log=None, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_status = on_status
        self._on_log = on_log
        self._cancel = threading.Event()
        self._games: list[GameItem] = []
        self._caches: list[LauncherCache] = []
        self._by_iid: dict[str, tuple[str, str]] = {}
        self._uid_to_iid: dict[str, str] = {}
        self._selected: set[str] = set()
        self._games_parent = ""
        self._busy = False
        self._close_steam_var = tk.BooleanVar(value=False)
        self._build_ui()

    def _status(self, t: str) -> None:
        if self._on_status:
            self._on_status(t)

    def _log(self, t: str) -> None:
        if self._on_log:
            self._on_log(t)

    def _build_ui(self) -> None:
        admin = "админ ✓" if is_admin() else "без админа — для удаления игр лучше run_admin.bat"
        ctk.CTkLabel(
            self,
            text=f"Отметь игры → «Удалить». Размеры из Steam/Epic + досчёт в фоне. ({admin})",
            text_color="#9aa0a6",
            wraplength=960,
            justify="left",
        ).pack(anchor="w", padx=4, pady=(4, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=6)
        ctk.CTkButton(bar, text="Обновить список", width=120, command=self.scan_list).pack(side="left", padx=2)
        ctk.CTkButton(bar, text="Сортировать по размеру", width=150, command=self._sort_games_tree).pack(side="left", padx=2)
        ctk.CTkButton(bar, text="Стоп", width=70, fg_color="#b91c1c", command=self._stop).pack(side="left", padx=2)
        ctk.CTkButton(bar, text="✓ Отметить", width=90, command=self._toggle_focus).pack(side="left", padx=2)

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        ctk.CTkEntry(bar, placeholder_text="Поиск…", textvariable=self._search_var, width=180).pack(side="right", padx=4)

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", padx=4)
        ctk.CTkCheckBox(
            opts,
            text="Закрыть Steam перед удалением игры (иначе файлы заняты; игру вырубит!)",
            variable=self._close_steam_var,
        ).pack(anchor="w")

        self._prog_label = ctk.CTkLabel(self, text="", text_color="#60a5fa", anchor="w")
        self._prog_label.pack(fill="x", padx=8)
        self._progress = ctk.CTkProgressBar(self)
        self._progress.pack(fill="x", padx=4, pady=2)
        self._progress.set(0)

        wrap = ctk.CTkFrame(self)
        wrap.pack(fill="both", expand=True, padx=4, pady=4)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Games.Treeview", background="#2b2b2b", fieldbackground="#2b2b2b", foreground="#eee", rowheight=24)
        style.configure("Games.Treeview.Heading", background="#3a3a3a", foreground="#fff")

        self._tree = ttk.Treeview(
            wrap,
            style="Games.Treeview",
            columns=("sel", "launcher", "size", "path"),
            show="tree headings",
            selectmode="extended",
        )
        self._tree.heading("#0", text="Игра")
        self._tree.heading("sel", text="✓")
        self._tree.heading("launcher", text="Лаунчер")
        self._tree.heading("size", text="Размер")
        self._tree.heading("path", text="Путь")
        self._tree.column("#0", width=220, stretch=True)
        self._tree.column("sel", width=32, anchor="center")
        self._tree.column("launcher", width=72)
        self._tree.column("size", width=96, anchor="e")
        self._tree.column("path", width=400)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._on_double_click)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", pady=8)
        self._total_label = ctk.CTkLabel(bottom, text="Отмечено: 0 · 0 B  |  Всего игр: —")
        self._total_label.pack(side="left", padx=4)
        ctk.CTkButton(bottom, text="Кэши лаунчеров", width=120, command=self._select_caches).pack(side="right", padx=2)
        ctk.CTkButton(
            bottom,
            text="Удалить отмеченное",
            width=160,
            fg_color="#b91c1c",
            command=self.delete_selected,
        ).pack(side="right", padx=4)

    def _on_double_click(self, event) -> None:
        self._toggle_focus()

    def _stop(self) -> None:
        self._cancel.set()
        self._prog_label.configure(text="Остановлено")

    def scan_list(self) -> None:
        if self._busy:
            self._cancel.set()
        self._cancel = threading.Event()
        self._busy = True
        self._progress.set(0)
        self._prog_label.configure(text="Читаю библиотеки…")

        def work() -> None:
            try:
                games = discover_games()
                caches = discover_launcher_caches()
                for c in caches:
                    if self._cancel.is_set():
                        break
                    measure_cache(c, self._cancel)
                self.after(0, lambda: self._fill_tree(games, caches))
            except Exception as e:
                self.after(0, lambda: self._fail(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _fail(self, err: str) -> None:
        self._busy = False
        messagebox.showerror("SCALY", err)

    def _fill_tree(self, games: list[GameItem], caches: list[LauncherCache]) -> None:
        self._games = games
        self._caches = caches
        self._selected.clear()
        self._by_iid.clear()
        self._uid_to_iid.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)

        if caches:
            parent = self._tree.insert("", "end", text="Кэши лаунчеров", open=True)
            for c in caches:
                self._insert_row(parent, c.uid, c.name, c.launcher, c, cache=True)

        self._games_parent = self._tree.insert("", "end", text=f"Игры ({len(games)})", open=True)
        for g in games:
            self._insert_row(self._games_parent, g.uid, g.name, g.launcher, g, cache=False)

        self._sort_games_tree()
        self._update_totals()
        known = sum(1 for g in games if g.size > 0)
        self._prog_label.configure(text=f"Размеров из манифестов: {known}/{len(games)} · досчёт…")
        self._apply_filter()
        self._start_background_sizes()

    def _insert_row(self, parent: str, uid: str, title: str, launcher: str, item, *, cache: bool) -> None:
        mark = "☑" if uid in self._selected else "☐"
        iid = self._tree.insert(
            parent,
            "end",
            text=title,
            values=(mark, launcher, _size_text(item), str(item.path)),
        )
        self._by_iid[iid] = ("cache" if cache else "game", uid)
        self._uid_to_iid[uid] = iid

    def _start_background_sizes(self) -> None:
        missing = [g for g in self._games if g.size <= 0]
        if not missing:
            self._busy = False
            self._progress.set(1)
            self._prog_label.configure(text="Готово")
            return

        cancel = self._cancel
        total = len(missing)
        done = [0]

        def work() -> None:
            for g in missing:
                if cancel.is_set():
                    break
                measure_game(g, cancel=cancel)
                done[0] += 1
                self.after(0, lambda gg=g, d=done[0], t=total: self._bg_size_update(gg, d, t))
            self.after(0, self._bg_done)

        threading.Thread(target=work, daemon=True).start()

    def _bg_size_update(self, g: GameItem, done: int, total: int) -> None:
        try:
            iid = self._uid_to_iid.get(g.uid)
            if iid:
                vals = list(self._tree.item(iid, "values"))
                if len(vals) >= 3:
                    vals[2] = _size_text(g)
                    self._tree.item(iid, values=vals)
            self._progress.set(done / max(1, total))
            self._prog_label.configure(text=f"Досчёт {done}/{total}")
            if done % 3 == 0:
                self._sort_games_tree()
                self._update_totals()
        except tk.TclError:
            pass

    def _bg_done(self) -> None:
        self._busy = False
        self._progress.set(1)
        self._sort_games_tree()
        self._update_totals()
        self._prog_label.configure(text="Список актуален")

    def _sort_games_tree(self) -> None:
        if not self._games_parent:
            return
        children = list(self._tree.get_children(self._games_parent))
        keyed = []
        for iid in children:
            info = self._by_iid.get(iid)
            if not info:
                continue
            it = self._uid_item(info[1])
            keyed.append((it.size if it else 0, iid))
        for i, (_sz, iid) in enumerate(sorted(keyed, key=lambda x: x[0], reverse=True)):
            self._tree.move(iid, self._games_parent, i)

    def _uid_item(self, uid: str) -> GameItem | LauncherCache | None:
        for g in self._games:
            if g.uid == uid:
                return g
        for c in self._caches:
            if c.uid == uid:
                return c
        return None

    def _toggle_uid(self, uid: str) -> None:
        if uid in self._selected:
            self._selected.discard(uid)
        else:
            self._selected.add(uid)
        iid = self._uid_to_iid.get(uid)
        if iid:
            vals = list(self._tree.item(iid, "values"))
            if vals:
                vals[0] = "☑" if uid in self._selected else "☐"
                self._tree.item(iid, values=vals)
        self._update_totals()

    def _toggle_focus(self) -> None:
        for iid in self._tree.selection():
            info = self._by_iid.get(iid)
            if info:
                self._toggle_uid(info[1])

    def _select_caches(self) -> None:
        for c in self._caches:
            if c.uid not in self._selected:
                self._toggle_uid(c.uid)

    def _apply_filter(self) -> None:
        q = self._search_var.get().strip().lower()
        for parent in self._tree.get_children(""):
            for child in list(self._tree.get_children(parent)):
                blob = (
                    self._tree.item(child, "text")
                    + " "
                    + " ".join(map(str, self._tree.item(child, "values")))
                ).lower()
                if not q or q in blob:
                    if self._tree.parent(child) != parent:
                        self._tree.move(child, parent, "end")
                else:
                    self._tree.detach(child)

    def _update_totals(self) -> None:
        sel_total = sum(self._uid_item(uid).size for uid in self._selected if self._uid_item(uid))
        all_games = sum(g.size for g in self._games)
        self._total_label.configure(
            text=f"Отмечено: {len(self._selected)} · {format_bytes(sel_total)}  |  "
            f"Всего игр: {format_bytes(all_games)} ({len(self._games)} шт.)"
        )

    def delete_selected(self) -> None:
        targets: list[tuple[str, Path, int]] = []
        for uid in self._selected:
            it = self._uid_item(uid)
            if not it:
                continue
            if isinstance(it, GameItem) and not is_safe_game_delete_path(it.path):
                messagebox.showwarning("SCALY", f"Небезопасный путь:\n{it.path}")
                return
            targets.append((it.name if hasattr(it, "name") else it.path.name, it.path, it.size))

        if not targets:
            messagebox.showinfo("SCALY", "Отметь игру двойным кликом")
            return

        lines = "\n".join(f"• {n} — {format_bytes(s)}" for n, _p, s in targets[:12])
        if len(targets) > 12:
            lines += f"\n… ещё {len(targets) - 12}"
        if not messagebox.askyesno(
            "Удалить с диска?",
            f"Будет удалено {len(targets)} папок:\n\n{lines}\n\n"
            "В библиотеке Steam/Epic запись может остаться — «Удалить» там отдельно.",
        ):
            return

        if not is_admin() and any(isinstance(self._uid_item(u), GameItem) for u in self._selected):
            if not messagebox.askyesno(
                "Нет прав админа",
                "Рекомендуется run_admin.bat.\nВсё равно попробовать?",
            ):
                return

        self._status("Удаление…")
        self._prog_label.configure(text="Удаление… не закрывай окно")

        def work() -> None:
            if self._close_steam_var.get():
                notes = try_close_steam()
                for n in notes:
                    self._log(f"[Steam] {n}")

            freed = 0
            reports = []
            for name, path, expected in targets:
                self.after(0, lambda n=name: self._prog_label.configure(text=f"Удаляю: {n}"))
                rep = force_delete_tree(path, expected_size=expected)
                reports.append((name, rep))
                if rep.success:
                    freed += rep.bytes_freed
                    self._log(f"[Игры] OK {name}: {format_bytes(rep.bytes_freed)}")
                else:
                    self._log(f"[Игры] FAIL {name}: {rep.hint or rep.errors}")

            self.after(0, lambda: self._delete_done(freed, reports))

        threading.Thread(target=work, daemon=True).start()

    def _delete_done(self, freed: int, reports) -> None:
        failed = [(n, r) for n, r in reports if not r.success]
        ok = len(reports) - len(failed)
        if failed:
            msg = f"Удалено: {ok} из {len(reports)}\nОсвобождено: {format_bytes(freed)}\n\nНе удалось:\n"
            msg += "\n".join(f"• {n}: {r.hint or (r.errors[0] if r.errors else 'ошибка')}" for n, r in failed[:5])
            messagebox.showwarning("SCALY — частично", msg)
        else:
            messagebox.showinfo("SCALY", f"Готово.\nОсвобождено ~{format_bytes(freed)}")
        self._status("Готово")
        self._prog_label.configure(text="")
        self.scan_list()

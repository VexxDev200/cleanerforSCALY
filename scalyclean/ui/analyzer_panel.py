import subprocess
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from scalyclean.core.utils import format_bytes
from scalyclean.modules.disk_analyzer import (
    PENDING_SIZE,
    find_largest_files,
    folder_scan,
    format_mtime,
    list_directory_entries,
    pct_bar,
)
from scalyclean.modules.extension_stats import ExtensionIndex, color_for_ext
from scalyclean.modules.volumes import VolumeInfo, list_volumes
from scalyclean.ui.treemap_canvas import TreemapCanvas, TreemapCell


class AnalyzerPanel(ctk.CTkFrame):
    def __init__(self, master, on_drive_change=None, on_status=None, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_drive_change = on_drive_change
        self._on_status = on_status
        self._cancel = threading.Event()
        self._scan_busy = False
        self._total_drive = 1
        self._used_drive = 1
        self._node_paths: dict[str, Path] = {}
        self._path_to_iid: dict[str, str] = {}
        self._node_meta: dict[str, dict] = {}
        self._ext_index = ExtensionIndex()
        self._scan_t0 = 0.0
        self._root_iid = ""
        self._treemap_focus_iid = ""
        self._ui_debounce_id: str | None = None

        self._build_ui()
        self._reload_volumes()

    def get_selected_drive(self) -> str:
        return self._drive_letter_from_choice(self._drive_var.get())

    def _set_status(self, text: str) -> None:
        if self._on_status:
            self._on_status(text)

    def _ui(self, fn) -> None:
        try:
            if self.winfo_exists():
                fn()
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        # --- Панель управления ---
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(bar, text="Том:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 6))
        self._drive_var = tk.StringVar(value="C:\\")
        self._drive_menu = ctk.CTkOptionMenu(
            bar, variable=self._drive_var, values=["C:\\"], width=280, command=self._on_drive_selected
        )
        self._drive_menu.pack(side="left")

        ctk.CTkButton(bar, text="▶ Анализ", width=110, fg_color="#1a7f37", command=self.run_analysis).pack(
            side="left", padx=(12, 4)
        )
        ctk.CTkButton(bar, text="Стоп", width=70, fg_color="#b91c1c", command=self.cancel_scan).pack(side="left", padx=4)
        self._time_label = ctk.CTkLabel(bar, text="", text_color="#9aa0a6")
        self._time_label.pack(side="right", padx=8)

        # --- Сводка (как WizTree) ---
        stats = ctk.CTkFrame(self)
        stats.pack(fill="x", pady=4)
        self._stat_labels: dict[str, ctk.CTkLabel] = {}
        for key, title in (
            ("total", "Всего"),
            ("used", "Занято"),
            ("free", "Свободно"),
            ("pct", "Заполнено"),
        ):
            cell = ctk.CTkFrame(stats, fg_color="#2b2b2b", corner_radius=8)
            cell.pack(side="left", expand=True, fill="x", padx=4, pady=4)
            ctk.CTkLabel(cell, text=title, text_color="#9aa0a6", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10, pady=(6, 0))
            lbl = ctk.CTkLabel(cell, text="—", font=ctk.CTkFont(size=15, weight="bold"))
            lbl.pack(anchor="w", padx=10, pady=(0, 8))
            self._stat_labels[key] = lbl

        self._progress = ctk.CTkProgressBar(self)
        self._progress.pack(fill="x", pady=(0, 6))
        self._progress.set(0)

        # --- Центр: дерево/файлы + расширения ---
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True)

        left = ctk.CTkFrame(mid)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self._view_tabs = ctk.CTkTabview(left, height=320)
        self._view_tabs.pack(fill="both", expand=True)
        tab_tree = self._view_tabs.add("Дерево")
        tab_files = self._view_tabs.add("Файлы")

        self._build_tree_tab(tab_tree)
        self._build_files_tab(tab_files)

        act = ctk.CTkFrame(left, fg_color="transparent")
        act.pack(fill="x", pady=4)
        ctk.CTkButton(act, text="📂 Проводник", width=100, command=self._open_in_explorer).pack(side="left", padx=2)
        ctk.CTkButton(act, text="Копировать путь", width=120, command=self._copy_path).pack(side="left", padx=2)
        ctk.CTkButton(act, text="Файлы папки", width=110, command=self._load_files_for_selection).pack(side="left", padx=2)

        right = ctk.CTkFrame(mid, width=300)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)
        ctk.CTkLabel(right, text="По расширениям", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=6, pady=4)
        ext_wrap = ctk.CTkFrame(right)
        ext_wrap.pack(fill="both", expand=True, padx=4, pady=4)
        self._ext_tree = ttk.Treeview(
            ext_wrap,
            columns=("pct", "size", "files"),
            show="tree headings",
            height=14,
        )
        self._ext_tree.heading("#0", text="Тип")
        self._ext_tree.heading("pct", text="%")
        self._ext_tree.heading("size", text="Размер")
        self._ext_tree.heading("files", text="Файлов")
        self._ext_tree.column("#0", width=100)
        self._ext_tree.column("pct", width=50, anchor="e")
        self._ext_tree.column("size", width=80, anchor="e")
        self._ext_tree.column("files", width=55, anchor="e")
        self._ext_tree.pack(fill="both", expand=True)

        # --- Карта WizTree ---
        map_frame = ctk.CTkFrame(self)
        map_frame.pack(fill="both", expand=True, padx=4, pady=(6, 4))
        ctk.CTkLabel(
            map_frame,
            text="Карта диска (WizTree) — клик по блоку = войти в папку",
            anchor="w",
            text_color="#9aa0a6",
        ).pack(fill="x", padx=4, pady=(4, 0))
        self._map_crumbs = ctk.CTkLabel(map_frame, text="", anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
        self._map_crumbs.pack(fill="x", padx=6, pady=2)
        self._treemap = TreemapCanvas(
            map_frame,
            on_activate=self._on_treemap_activate,
            bg="#121212",
            height=300,
        )
        self._treemap.pack(fill="both", expand=True, padx=2, pady=4)

    def _build_tree_tab(self, parent) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Scaly.Treeview", background="#2b2b2b", fieldbackground="#2b2b2b", foreground="#e8e8e8", rowheight=24)
        style.configure("Scaly.Treeview.Heading", background="#3c3c3c", foreground="#ffffff")

        self._tree = ttk.Treeview(
            wrap,
            style="Scaly.Treeview",
            columns=("pct", "size", "items", "modified"),
            show="tree headings",
        )
        self._tree.heading("#0", text="Папка")
        self._tree.heading("pct", text="Доля")
        self._tree.heading("size", text="Размер")
        self._tree.heading("items", text="Элементов")
        self._tree.heading("modified", text="Изменено")
        self._tree.column("#0", width=220, stretch=True)
        self._tree.column("pct", width=130)
        self._tree.column("size", width=88, anchor="e")
        self._tree.column("items", width=72, anchor="e")
        self._tree.column("modified", width=120, anchor="w")
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_files_tab(self, parent) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        self._files_tree = ttk.Treeview(
            wrap,
            columns=("size", "modified"),
            show="tree headings",
        )
        self._files_tree.heading("#0", text="Файл")
        self._files_tree.heading("size", text="Размер")
        self._files_tree.heading("modified", text="Изменено")
        self._files_tree.column("#0", width=360, stretch=True)
        self._files_tree.column("size", width=90, anchor="e")
        self._files_tree.column("modified", width=130)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self._files_tree.yview)
        self._files_tree.configure(yscrollcommand=ysb.set)
        self._files_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    def _reload_volumes(self) -> None:
        vols = list_volumes()
        if not vols:
            return
        labels = []
        self._vol_map: dict[str, VolumeInfo] = {}
        for v in vols:
            name = v.label or "Локальный диск"
            text = f"[{v.letter.rstrip(chr(92))}] {name}"
            labels.append(text)
            self._vol_map[text] = v
        self._drive_menu.configure(values=labels)
        self._drive_var.set(labels[0])
        self._apply_volume_info(vols[0])

    def _on_drive_selected(self, choice: str) -> None:
        v = self._vol_map.get(choice)
        if v:
            self._apply_volume_info(v)
        if self._on_drive_change:
            self._on_drive_change(self._drive_letter_from_choice(choice))

    def _drive_letter_from_choice(self, choice: str) -> str:
        v = self._vol_map.get(choice)
        return v.letter if v else "C:\\"

    def _apply_volume_info(self, v: VolumeInfo) -> None:
        self._total_drive = max(1, v.total)
        self._used_drive = max(1, v.used)
        self._stat_labels["total"].configure(text=format_bytes(v.total))
        self._stat_labels["used"].configure(text=f"{format_bytes(v.used)} ({v.percent:.1f}%)")
        self._stat_labels["free"].configure(text=format_bytes(v.free))
        self._stat_labels["pct"].configure(text=f"{v.percent:.1f}%")

    def cancel_scan(self) -> None:
        self._cancel.set()
        self._set_status("Остановка…")

    def run_analysis(self) -> None:
        if self._scan_busy:
            self._cancel.set()
            self.after(200, self.run_analysis)
            return

        self._cancel = threading.Event()
        cancel = self._cancel
        self._scan_busy = True
        self._scan_t0 = time.perf_counter()
        self._ext_index = ExtensionIndex()
        self._progress.set(0)
        self._time_label.configure(text="Сканирование…")

        drive = self._drive_letter_from_choice(self._drive_var.get())
        choice = self._drive_var.get()
        v = self._vol_map.get(choice)
        root_label = choice if choice else drive

        self._clear_tree()
        self._root_iid = self._tree.insert(
            "",
            "end",
            text=root_label,
            values=(pct_bar(100.0, 8), format_bytes(self._used_drive), "—", "—"),
            open=True,
        )
        self._node_paths[self._root_iid] = Path(drive)
        self._node_meta[self._root_iid] = {"size": self._used_drive}

        entries = list_directory_entries(Path(drive))
        pending: list[Path] = []
        for node in entries:
            iid = self._insert_child(self._root_iid, node, parent_size=self._used_drive)
            if node.pending:
                pending.append(node.path)
        if not entries:
            self._finish_scan()
            return

        self._treemap_focus_iid = self._root_iid
        self._refresh_treemap_for(self._root_iid)
        self._set_status(f"Найдено {len(entries)} в корне · считаю папки…")
        total_pending = max(1, len(pending))
        done = [0]

        def scan_folder(path: Path):
            return path, folder_scan(path, cancel=cancel, collect_extensions=False)

        def work() -> None:
            try:
                if not pending:
                    self.after(0, lambda: self._ui(self._finish_scan))
                    return
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(scan_folder, p) for p in pending]
                    for fut in as_completed(futures):
                        if cancel.is_set():
                            break
                        try:
                            path, result = fut.result()
                        except Exception:
                            continue
                        done[0] += 1
                        prog = done[0] / total_pending
                        self.after(
                            0,
                            lambda p=path, r=result, pr=prog: self._ui(
                                lambda: self._on_folder_scanned(p, r, pr)
                            ),
                        )
                self.after(0, lambda: self._ui(self._finish_scan))
            except Exception:
                self.after(0, lambda: self._ui(self._finish_scan))

        threading.Thread(target=work, daemon=True).start()

    def _clear_tree(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._node_paths.clear()
        self._path_to_iid.clear()
        self._node_meta.clear()
        for iid in self._ext_tree.get_children():
            self._ext_tree.delete(iid)

    def _insert_child(self, parent_iid: str, node, parent_size: int) -> str:
        if node.pending:
            pct = "скан…"
            size_txt = "…"
            items = "—"
            mod = "—"
        else:
            pct = pct_bar(100.0 * node.size / parent_size if parent_size else 0, 8)
            size_txt = format_bytes(node.size)
            items = str(node.file_count)
            mod = "—"

        text = node.name + (" ⚠" if node.error else "")
        iid = self._tree.insert(
            parent_iid,
            "end",
            text=text,
            values=(pct, size_txt, items, mod),
        )
        self._node_paths[iid] = node.path
        self._path_to_iid[str(node.path).lower()] = iid
        self._node_meta[iid] = {"size": node.size if not node.pending else 0}
        if node.path.is_dir() and not node.error:
            self._tree.insert(iid, "end", text="…")
        return iid

    def _on_folder_scanned(self, path: Path, result, progress: float) -> None:
        iid = self._path_to_iid.get(str(path).lower())
        if iid:
            pct = pct_bar(100.0 * result.size / self._used_drive, 8)
            items = f"{result.file_count + result.folder_count:,}".replace(",", " ")
            self._tree.item(
                iid,
                values=(pct, format_bytes(result.size), items, format_mtime(result.latest_mtime)),
            )
            self._node_meta[iid] = {
                "size": result.size,
                "files": result.file_count,
                "folders": result.folder_count,
            }
        self._progress.set(progress)
        elapsed = time.perf_counter() - self._scan_t0
        self._time_label.configure(text=f"{elapsed:.1f} с")
        self._schedule_repaint_root()

    def _resort_children(self, parent_iid: str) -> None:
        children = list(self._tree.get_children(parent_iid))
        if not children:
            return

        def key(iid: str) -> int:
            return self._node_meta.get(iid, {}).get("size", 0)

        for i, iid in enumerate(sorted(children, key=key, reverse=True)):
            self._tree.move(iid, parent_iid, i)

    def _refresh_extensions(self) -> None:
        for iid in self._ext_tree.get_children():
            self._ext_tree.delete(iid)
        total = max(1, self._ext_index.total_size)
        for idx, (ext, st) in enumerate(self._ext_index.top(25)):
            pct = 100.0 * st.size / total
            color = color_for_ext(ext, idx)
            self._ext_tree.insert(
                "",
                "end",
                text=f"  {ext}",
                values=(f"{pct:.1f}%", format_bytes(st.size), st.count),
            )

    def _breadcrumb(self, iid: str) -> str:
        chain: list[str] = []
        cur = iid
        while cur:
            txt = self._tree.item(cur, "text")
            if txt:
                chain.append(txt.split("(")[0].strip())
            cur = self._tree.parent(cur)
        chain.reverse()
        return " › ".join(chain)

    def _refresh_treemap_for(self, parent_iid: str) -> None:
        if not parent_iid:
            self._treemap.set_cells([])
            return
        cells: list[TreemapCell] = []
        for idx, child in enumerate(self._tree.get_children(parent_iid)):
            path = self._node_paths.get(child)
            if not path:
                continue
            size = int(self._node_meta.get(child, {}).get("size") or 0)
            if size <= 0:
                size = 1
            label = self._tree.item(child, "text").replace(" ⚠", "")
            cells.append(
                TreemapCell(
                    label=label,
                    size=size,
                    path=str(path),
                    color=color_for_ext(f".{idx}", idx),
                )
            )
        self._map_crumbs.configure(text=self._breadcrumb(parent_iid))
        self._treemap.set_cells(cells)

    def _on_tree_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        path = self._node_paths.get(iid)
        if path and path.is_dir():
            self._treemap_focus_iid = iid
            self._ensure_children_loaded(iid)
            self._refresh_treemap_for(iid)

    def _on_treemap_activate(self, cell: TreemapCell) -> None:
        key = cell.path.lower()
        iid = self._path_to_iid.get(key)
        if not iid:
            return
        self._tree.selection_set(iid)
        self._tree.focus(iid)
        self._tree.see(iid)
        path = self._node_paths.get(iid)
        if path and path.is_dir():
            self._treemap_focus_iid = iid
            self._ensure_children_loaded(iid)
            self._refresh_treemap_for(iid)
            try:
                self._tree.item(iid, open=True)
            except tk.TclError:
                pass

    def _ensure_children_loaded(self, iid: str) -> None:
        children = self._tree.get_children(iid)
        if not children:
            return
        if self._tree.item(children[0], "text") != "…":
            return
        path = self._node_paths.get(iid)
        if not path or not path.is_dir():
            return
        for c in children:
            self._tree.delete(c)
        parent_size = self._node_meta.get(iid, {}).get("size") or self._used_drive
        entries = list_directory_entries(path)
        pending: list[Path] = []
        for node in entries:
            self._insert_child(iid, node, parent_size=parent_size)
            if node.pending:
                pending.append(node.path)
        self._resort_children(iid)
        if pending:
            self._cancel.clear()
            cancel = self._cancel

            def _scan_one(p: Path):
                return p, folder_scan(p, cancel=cancel, collect_extensions=False)

            def work() -> None:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    futs = [pool.submit(_scan_one, p) for p in pending]
                    for fut in as_completed(futs):
                        if cancel.is_set():
                            break
                        try:
                            p, result = fut.result()
                        except Exception:
                            continue
                        self.after(0, lambda path=p, r=result: self._on_child_scanned(path, r))
                self.after(0, lambda: self._ui(lambda: self._refresh_treemap_for(iid)))

            threading.Thread(target=work, daemon=True).start()
        else:
            self._refresh_treemap_for(iid)

    def _schedule_repaint_root(self) -> None:
        if self._ui_debounce_id:
            try:
                self.after_cancel(self._ui_debounce_id)
            except tk.TclError:
                pass
        self._ui_debounce_id = self.after(250, self._repaint_root)

    def _repaint_root(self) -> None:
        self._ui_debounce_id = None
        self._resort_children(self._root_iid)
        focus = self._treemap_focus_iid or self._root_iid
        self._refresh_treemap_for(focus)

    def _finish_scan(self) -> None:
        self._scan_busy = False
        self._progress.set(1)
        elapsed = time.perf_counter() - self._scan_t0
        self._time_label.configure(text=f"Готово за {elapsed:.1f} с")
        self._repaint_root()
        self._set_status("Анализ завершён · раскрывай папки для деталей")

    def _on_tree_open(self, _event) -> None:
        iid = self._tree.focus() or (self._tree.selection()[0] if self._tree.selection() else "")
        if not iid or iid == self._root_iid:
            return
        children = self._tree.get_children(iid)
        if not children or self._tree.item(children[0], "text") != "…":
            return
        path = self._node_paths.get(iid)
        if not path or not path.is_dir():
            return
        for c in children:
            self._tree.delete(c)

        parent_size = self._node_meta.get(iid, {}).get("size") or self._used_drive
        entries = list_directory_entries(path)
        pending: list[Path] = []
        for node in entries:
            self._insert_child(iid, node, parent_size=parent_size)
            if node.pending:
                pending.append(node.path)

        if not pending:
            self._resort_children(iid)
            return

        cancel = self._cancel

        def _scan_one(p: Path):
            return p, folder_scan(p, cancel=cancel, collect_extensions=False)

        def work() -> None:
            with ThreadPoolExecutor(max_workers=1) as pool:
                futs = [pool.submit(_scan_one, p) for p in pending]
                for fut in as_completed(futs):
                    if cancel.is_set():
                        break
                    try:
                        p, result = fut.result()
                    except Exception:
                        continue
                    self.after(0, lambda path=p, r=result: self._on_child_scanned(path, r))
            self.after(0, lambda pid=iid: self._ui(lambda: self._resort_children(pid)))

        threading.Thread(target=work, daemon=True).start()

    def _on_child_scanned(self, path: Path, result) -> None:
        iid = self._path_to_iid.get(str(path).lower())
        if not iid:
            return
        parent = self._tree.parent(iid)
        parent_size = self._node_meta.get(parent, {}).get("size") or self._used_drive
        pct = pct_bar(100.0 * result.size / parent_size if parent_size else 0, 8)
        items = f"{result.file_count + result.folder_count:,}".replace(",", " ")
        self._tree.item(
            iid,
            values=(pct, format_bytes(result.size), items, format_mtime(result.latest_mtime)),
        )
        self._node_meta[iid] = {"size": result.size, "files": result.file_count, "folders": result.folder_count}
        if self._tree.parent(iid) == self._treemap_focus_iid:
            self._refresh_treemap_for(self._treemap_focus_iid)

    def _load_files_for_selection(self) -> None:
        path = self._selected_path()
        if not path:
            path = Path(self._drive_letter_from_choice(self._drive_var.get()))
        if path.is_file():
            path = path.parent
        for iid in self._files_tree.get_children():
            self._files_tree.delete(iid)

        if path.is_dir():
            try:
                entries = list_directory_entries(path)
            except OSError:
                entries = []
            files = [n for n in entries if not n.pending and n.file_count == 1]
            files.sort(key=lambda n: n.size, reverse=True)
            for n in files[:500]:
                self._files_tree.insert(
                    "",
                    "end",
                    text=n.name,
                    values=(format_bytes(n.size), "—"),
                )
        self._view_tabs.set("Файлы")

        cancel = self._cancel

        def work() -> None:
            big = find_largest_files(path, limit=80, cancel=cancel)
            self.after(0, lambda: self._show_large_files(big))

        threading.Thread(target=work, daemon=True).start()

    def _show_large_files(self, files) -> None:
        for iid in self._files_tree.get_children():
            self._files_tree.delete(iid)
        for lf in files:
            self._files_tree.insert(
                "",
                "end",
                text=str(lf.path),
                values=(format_bytes(lf.size), format_mtime(lf.mtime)),
            )

    def _selected_path(self) -> Path | None:
        sel = self._tree.selection()
        iid = sel[0] if sel else self._tree.focus()
        if not iid:
            return None
        return self._node_paths.get(iid)

    def _open_in_explorer(self) -> None:
        p = self._selected_path()
        if not p:
            return
        subprocess.Popen(["explorer", str(p if p.is_dir() else p.parent)])

    def _copy_path(self) -> None:
        p = self._selected_path()
        if not p:
            return
        self.clipboard_clear()
        self.clipboard_append(str(p))

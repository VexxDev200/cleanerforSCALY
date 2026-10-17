"""Анализ занятости диска (идея WizTree / TreeSize): дерево папок, топ файлов, быстрый обзор корня."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from scalyclean.modules.extension_stats import ExtensionIndex


PENDING_SIZE = -1


@dataclass
class ScanNode:
    path: Path
    name: str
    size: int
    file_count: int = 0
    children: list[ScanNode] = field(default_factory=list)
    error: str | None = None

    @property
    def pending(self) -> bool:
        return self.size == PENDING_SIZE


@dataclass
class LargeFile:
    path: Path
    size: int
    mtime: float = 0.0


@dataclass
class FolderScanResult:
    size: int
    file_count: int
    folder_count: int
    latest_mtime: float | None
    extensions: ExtensionIndex


ProgressCb = Callable[[str, float], None]


def _folder_immediate_size(path: Path, cancel: threading.Event | None) -> tuple[int, int]:
    """Размер файлов только в этой папке (без рекурсии в подпапки)."""
    total = 0
    count = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if cancel and cancel.is_set():
                    break
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                        count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        pass
                except OSError:
                    continue
    except OSError:
        pass
    return total, count


def folder_scan(
    path: Path,
    cancel: threading.Event | None = None,
    on_progress: ProgressCb | None = None,
    _files_seen: list[int] | None = None,
    *,
    collect_extensions: bool = False,
) -> FolderScanResult:
    if _files_seen is None:
        _files_seen = [0]
    total = 0
    file_count = 0
    folder_count = 0
    latest: float | None = None
    ext = ExtensionIndex() if collect_extensions else None
    stack: list[Path] = [path]
    while stack:
        if cancel and cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel and cancel.is_set():
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            total += st.st_size
                            file_count += 1
                            if ext is not None:
                                ext.add_file(entry.name, st.st_size)
                            if latest is None or st.st_mtime > latest:
                                latest = st.st_mtime
                            _files_seen[0] += 1
                            if on_progress and _files_seen[0] % 800 == 0:
                                on_progress(str(current), min(0.99, _files_seen[0] / 500_000))
                        elif entry.is_dir(follow_symlinks=False):
                            folder_count += 1
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return FolderScanResult(total, file_count, folder_count, latest, ext or ExtensionIndex())


def folder_total_size(
    path: Path,
    cancel: threading.Event | None = None,
    on_progress: ProgressCb | None = None,
    _files_seen: list[int] | None = None,
) -> tuple[int, int]:
    r = folder_scan(path, cancel=cancel, on_progress=on_progress, _files_seen=_files_seen)
    return r.size, r.file_count


def format_mtime(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except (OSError, ValueError):
        return "—"


def pct_bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "█" * filled + "░" * (width - filled) + f" {pct:.1f}%"


def list_directory_entries(folder: Path) -> list[ScanNode]:
    """Мгновенно показать содержимое: файлы с размером, папки — size=PENDING_SIZE."""
    nodes: list[ScanNode] = []
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError as e:
        return [ScanNode(path=folder, name=folder.name or str(folder), size=0, error=str(e))]

    for entry in entries:
        p = Path(entry.path)
        try:
            if entry.is_file(follow_symlinks=False):
                sz = entry.stat(follow_symlinks=False).st_size
                nodes.append(ScanNode(path=p, name=entry.name, size=sz, file_count=1))
            elif entry.is_dir(follow_symlinks=False):
                nodes.append(ScanNode(path=p, name=entry.name, size=PENDING_SIZE, file_count=0))
        except OSError as e:
            nodes.append(ScanNode(path=p, name=entry.name, size=0, error=str(e)))

    nodes.sort(key=lambda n: (n.pending, -n.size, n.name.lower()))
    return nodes


def scan_root_overview(drive: str, cancel: threading.Event | None = None) -> list[ScanNode]:
    """Совместимость: полный обзор корня (медленно)."""
    root = Path(drive)
    nodes = list_directory_entries(root)
    out: list[ScanNode] = []
    for node in nodes:
        if cancel and cancel.is_set():
            break
        if node.pending:
            sz, fc = folder_total_size(node.path, cancel=cancel)
            out.append(
                ScanNode(path=node.path, name=node.name, size=sz, file_count=fc, error=node.error)
            )
        else:
            out.append(node)
    out.sort(key=lambda n: n.size, reverse=True)
    return out


def list_children_sizes(folder: Path, cancel: threading.Event | None = None) -> list[ScanNode]:
    return list_directory_entries(folder)


def find_largest_files(
    root: Path,
    limit: int = 100,
    cancel: threading.Event | None = None,
) -> list[LargeFile]:
    import heapq

    heap: list[tuple[int, str]] = []
    stack: list[Path] = [root]
    while stack:
        if cancel and cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel and cancel.is_set():
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            sz = st.st_size
                            path = entry.path
                            item = (sz, st.st_mtime, path)
                            if len(heap) < limit:
                                heapq.heappush(heap, item)
                            elif sz > heap[0][0]:
                                heapq.heapreplace(heap, item)
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    out = [LargeFile(path=Path(p), size=s, mtime=mt) for s, mt, p in heap]
    out.sort(key=lambda x: x.size, reverse=True)
    return out


def target_matches_drive(path: Path, drive: str) -> bool:
    if not drive:
        return True
    d = drive.upper().rstrip("\\")
    if not d.endswith(":"):
        d += ":"
    try:
        resolved = str(path.resolve()).upper()
    except OSError:
        resolved = str(path).upper()
    return resolved.startswith(d + "\\") or resolved.startswith(d + "/")

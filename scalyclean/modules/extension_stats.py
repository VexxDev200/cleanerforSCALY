from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtensionStats:
    size: int = 0
    count: int = 0


@dataclass
class ExtensionIndex:
    by_ext: dict[str, ExtensionStats] = field(default_factory=dict)

    def add_file(self, name: str, size: int) -> None:
        ext = _normalize_ext(name)
        st = self.by_ext.setdefault(ext, ExtensionStats())
        st.size += size
        st.count += 1

    def merge(self, other: ExtensionIndex) -> None:
        for ext, st in other.by_ext.items():
            mine = self.by_ext.setdefault(ext, ExtensionStats())
            mine.size += st.size
            mine.count += st.count

    def top(self, limit: int = 30) -> list[tuple[str, ExtensionStats]]:
        items = sorted(self.by_ext.items(), key=lambda x: x[1].size, reverse=True)
        return items[:limit]

    @property
    def total_size(self) -> int:
        return sum(s.size for s in self.by_ext.values())


def _normalize_ext(name: str) -> str:
    if "." not in name:
        return "(без расширения)"
    ext = name.rsplit(".", 1)[-1].lower()
    if len(ext) > 12:
        return "(без расширения)"
    return f".{ext}"


# WizTree-подобная палитра
EXT_COLORS: dict[str, str] = {
    ".dll": "#e11d48",
    ".exe": "#f97316",
    ".sys": "#fb923c",
    ".rar": "#a855f7",
    ".zip": "#9333ea",
    ".7z": "#7c3aed",
    ".mp4": "#22c55e",
    ".mkv": "#16a34a",
    ".avi": "#15803d",
    ".mp3": "#06b6d4",
    ".wav": "#0891b2",
    ".jpg": "#eab308",
    ".png": "#ca8a04",
    ".jpeg": "#facc15",
    ".gif": "#fde047",
    ".pdf": "#3b82f6",
    ".doc": "#2563eb",
    ".docx": "#1d4ed8",
    ".tmp": "#64748b",
    ".log": "#94a3b8",
    ".pak": "#ec4899",
    ".bin": "#f43f5e",
    ".dat": "#d946ef",
    ".json": "#6366f1",
    ".xml": "#818cf8",
    ".py": "#14b8a6",
    ".js": "#fbbf24",
    ".ts": "#2dd4bf",
    ".cpp": "#60a5fa",
    ".h": "#93c5fd",
    ".lib": "#c084fc",
    ".cab": "#e879f9",
    ".msi": "#f472b6",
    ".iso": "#4ade80",
    "(без расширения)": "#6b7280",
}

_FALLBACK = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#0891b2", "#ca8a04", "#dc2626"]


def color_for_ext(ext: str, index: int = 0) -> str:
    if ext in EXT_COLORS:
        return EXT_COLORS[ext]
    return _FALLBACK[index % len(_FALLBACK)]

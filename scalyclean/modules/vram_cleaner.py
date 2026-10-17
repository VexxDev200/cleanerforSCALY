"""VRAM: кэши GPU — удаление с учётом занятых файлов (WinError 32)."""

import ctypes
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from scalyclean.core.utils import CleanResult, dir_size
from scalyclean.core.win_delete import clear_folder_best_effort


@dataclass
class GpuAdapterInfo:
    name: str
    adapter_ram_mb: int | None


@dataclass
class VramReport:
    cache_size: int
    gpu_processes: list[tuple[int, str, int]]
    errors: list[str]
    adapters: list[GpuAdapterInfo]


def _wmi_gpu_adapters() -> list[GpuAdapterInfo]:
    adapters: list[GpuAdapterInfo] = []
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json -Compress",
        ]
        out = subprocess.check_output(cmd, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        text = out.decode("utf-8", errors="replace").strip()
        if not text:
            return adapters
        import json

        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            name = str(item.get("Name") or "GPU")
            ram = item.get("AdapterRAM")
            mb = None
            if isinstance(ram, int) and ram > 0:
                mb = ram // (1024 * 1024)
            adapters.append(GpuAdapterInfo(name=name, adapter_ram_mb=mb))
    except Exception:
        pass
    return adapters


def gpu_heavy_processes(min_working_set_mb: int = 200) -> list[tuple[int, str, int]]:
    out: list[tuple[int, str, int]] = []
    threshold = min_working_set_mb * 1024 * 1024
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            mi = p.info.get("memory_info")
            if not mi:
                continue
            ws = getattr(mi, "ws", 0) or 0
            if ws >= threshold:
                out.append((p.info["pid"], p.info.get("name") or "?", ws // (1024 * 1024)))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    out.sort(key=lambda x: x[2], reverse=True)
    return out[:25]


def vram_cache_paths() -> list[tuple[str, Path]]:
    import os

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    appdata = Path(os.environ.get("APPDATA", ""))
    return [
        ("DirectX D3DSCache", local / "D3DSCache"),
        ("NVIDIA DXCache", local / "NVIDIA" / "DXCache"),
        ("NVIDIA GLCache", local / "NVIDIA" / "GLCache"),
        ("AMD DxCache", local / "AMD" / "DxCache"),
        ("Intel ShaderCache", local / "Intel" / "ShaderCache"),
        ("Vulkan cache", appdata / "Khronos" / "Vulkan"),
    ]


def scan_vram_caches() -> int:
    total = 0
    for _label, path in vram_cache_paths():
        total += dir_size(path)
    return total


def clean_vram_caches(*, gentle: bool = True) -> CleanResult:
    # gentle=True: никогда не убиваем Steam/Epic/игры — только свободные файлы кэша
    freed = 0
    files = 0
    locked_total = 0
    scheduled = 0
    errors: list[str] = []

    for label, path in vram_cache_paths():
        if not path.exists():
            continue
        rep = clear_folder_best_effort(path, keep_root=True)
        freed += rep.bytes_freed
        files += rep.files_removed
        locked_total += rep.files_locked
        scheduled += rep.scheduled_reboot
        if rep.notes:
            errors.append(f"{label}: {rep.notes[0]}")

    if locked_total:
        errors.append(
            f"Итого занято GPU/драйвером: {locked_total} файлов — закрой игры и повтори, "
            f"или перезагрузи ПК ({scheduled} в очереди на удаление)"
        )
    return CleanResult("GPU shader / VRAM кэши", freed, files, errors)


def inspect_vram() -> VramReport:
    return VramReport(
        cache_size=scan_vram_caches(),
        gpu_processes=gpu_heavy_processes(),
        errors=[],
        adapters=_wmi_gpu_adapters(),
    )


def flush_dwm() -> list[str]:
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        hr = dwmapi.DwmFlush()
        if hr != 0:
            return [f"DwmFlush HRESULT={hr}"]
    except OSError:
        pass
    except Exception as e:
        return [str(e)]
    return []

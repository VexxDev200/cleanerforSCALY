"""Защита релизного exe: целостность, антиотладка, фоновый watchdog."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import random
import sys
import threading
import time
from pathlib import Path

from scalyclean._integrity import BUILD_STAMP, FILE_HASHES, HMAC_SIG

_WATCHDOG: threading.Thread | None = None
_STOP = threading.Event()


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _skip() -> bool:
    if os.environ.get("SCALY_SKIP_PROTECTION", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    if not _frozen():
        return True
    return False


def _bundle_root() -> Path:
    if _frozen():
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return Path(__file__).resolve().parents[2]


def _signing_key() -> bytes:
    raw = bytes(
        (
            0xF2,
            0x9C,
            0x11,
            0xA8,
            0x55,
            0x3E,
            0xC0,
            0x7D,
            0x18,
            0xB4,
            0x62,
            0x91,
            0x0F,
            0xD3,
            0x44,
            0xE6,
            0x29,
            0x5A,
            0x83,
            0x1C,
            0xAF,
            0x70,
            0x36,
            0xBB,
            0x4E,
            0x02,
            0x97,
            0x6D,
            0xCA,
            0x51,
            0x08,
            0xFE,
        )
    )
    return hashlib.sha256(raw).digest()


def _expected_hmac(hashes: dict[str, str], stamp: str) -> str:
    payload = json.dumps(
        {"stamp": stamp, "files": hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()


def verify_integrity() -> bool:
    if BUILD_STAMP == "dev" or not FILE_HASHES:
        return not _frozen()
    if not HMAC_SIG:
        return False
    if _expected_hmac(FILE_HASHES, BUILD_STAMP) != HMAC_SIG:
        return False
    root = _bundle_root()
    for rel, expected in FILE_HASHES.items():
        path = root / rel.replace("/", os.sep)
        if not path.is_file():
            continue
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            return False
    return True


def _kernel32() -> ctypes.WinDLL:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _ntdll() -> ctypes.WinDLL:
    return ctypes.WinDLL("ntdll", use_last_error=True)


def anti_debug() -> bool:
    try:
        k32 = _kernel32()
        if k32.IsDebuggerPresent():
            return True
        present = ctypes.c_int(0)
        if k32.CheckRemoteDebuggerPresent(k32.GetCurrentProcess(), ctypes.byref(present)):
            if present.value:
                return True
    except Exception:
        pass

    try:
        ntdll = _ntdll()
        ProcessDebugPort = 7
        port = ctypes.c_ulong(0)
        status = ntdll.NtQueryInformationProcess(
            _kernel32().GetCurrentProcess(),
            ProcessDebugPort,
            ctypes.byref(port),
            ctypes.sizeof(port),
            None,
        )
        if status == 0 and port.value != 0:
            return True
    except Exception:
        pass

    t0 = time.perf_counter()
    try:
        _kernel32().OutputDebugStringW("scaly")
    except Exception:
        pass
    if time.perf_counter() - t0 > 0.08:
        return True
    return False


_HOSTILE_EXE = frozenset(
    {
        "x64dbg.exe",
        "x32dbg.exe",
        "ollydbg.exe",
        "ida64.exe",
        "ida.exe",
        "idag.exe",
        "idaw.exe",
        "cheatengine-x86_64.exe",
        "cheatengine.exe",
        "dnspy.exe",
        "ilspy.exe",
        "pestudio.exe",
        "httpdebuggerui.exe",
    }
)


def hostile_tools_running() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in _HOSTILE_EXE:
                return True
    except Exception:
        pass
    return False


def _parent_suspicious() -> bool:
    try:
        import psutil

        me = psutil.Process()
        parent = me.parent()
        if not parent:
            return False
        pname = (parent.name() or "").lower()
        if pname in _HOSTILE_EXE:
            return True
        if pname in ("python.exe", "pythonw.exe") and _frozen():
            return True
    except Exception:
        pass
    return False


def run_checks() -> str | None:
    if _skip():
        return None
    if not verify_integrity():
        return "integrity"
    if anti_debug():
        return "debug"
    if hostile_tools_running():
        return "tools"
    if _parent_suspicious():
        return "parent"
    return None


def _fail(reason: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "SCALY Cleaner: среда выполнения не прошла проверку безопасности.\n"
            "Закрой отладчики и запусти официальный билд снова.",
            "SCALY Cleaner",
            0x10,
        )
    except Exception:
        pass
    os._exit(1)


def _watchdog_loop() -> None:
    while not _STOP.wait(timeout=random.uniform(35.0, 75.0)):
        reason = run_checks()
        if reason:
            _fail(reason)


def install_protection() -> None:
    global _WATCHDOG
    reason = run_checks()
    if reason:
        _fail(reason)
    if _skip():
        return
    if _WATCHDOG and _WATCHDOG.is_alive():
        return
    _WATCHDOG = threading.Thread(target=_watchdog_loop, name="scaly-guard", daemon=True)
    _WATCHDOG.start()


def shutdown_protection() -> None:
    _STOP.set()

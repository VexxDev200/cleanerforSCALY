import ctypes
import sys
from pathlib import Path


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if is_admin():
        return
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        exe = Path(sys.executable).resolve()
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe),
            params,
            str(exe.parent),
            1,
        )
    else:
        script = Path(sys.argv[0]).resolve()
        root = script.parent
        params = f'"{script}"'
        if len(sys.argv) > 1:
            params += " " + " ".join(f'"{a}"' for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            params,
            str(root),
            1,
        )
    sys.exit(0)

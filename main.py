"""
SCALY Cleaner — запуск GUI.
Для полного RAM standby purge: правый клик → «Запуск от имени администратора»
или run_admin.bat
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scalyclean.core.crash_guard import install_crash_guard
from scalyclean.core.protection import install_protection


def main() -> None:
    install_crash_guard()
    install_protection()
    from scalyclean.core.admin import is_admin, relaunch_as_admin

    if not is_admin():
        relaunch_as_admin()
    from scalyclean.app import run_app

    run_app()


if __name__ == "__main__":
    main()

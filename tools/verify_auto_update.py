"""
Проверка цепочки автообновления (manifest + ссылка на exe).
  python tools/verify_auto_update.py
  set SCALY_UPDATE_TEST_VERSION=1.0.0 && python tools/verify_auto_update.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scalyclean import __version__
from scalyclean.core.updater import (  # noqa: E402
    check_for_update,
    diagnose_update,
    version_gt,
)


def main() -> int:
    import os

    if "--simulate-old" in sys.argv:
        os.environ["SCALY_UPDATE_TEST_VERSION"] = "1.0.0"
    else:
        os.environ.pop("SCALY_UPDATE_TEST_VERSION", None)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    d = diagnose_update()
    print("=== SCALY auto-update verify ===")
    for line in d.summary_lines():
        print(line)

    info = check_for_update()
    if info:
        print(f"\nКнопка «Обновить» в exe: ДА -> v{info.version} ({info.source})")
    else:
        print("\nКнопка «Обновить» в exe: нет (версия актуальна или manifest недоступен)")

    import json

    pkg_ver = __version__
    local_manifest = json.loads((ROOT / "releases" / "version.json").read_text(encoding="utf-8"))
    manifest_ver = str(local_manifest["version"])
    if pkg_ver != manifest_ver:
        print(f"! Локально: код v{pkg_ver} != releases/version.json v{manifest_ver}")
        print("  Запусти publish_all.bat из корня проекта")
        return 1

    if d.remote_version and version_gt(pkg_ver, d.remote_version):
        print(
            f"! На GitHub manifest v{d.remote_version}, а сборка v{pkg_ver} — "
            "у людей с exe кнопки не будет."
        )
        print("  git push origin main  (файл releases/version.json)")
        print("  затем tools\\setup_github_and_publish.ps1")
        return 1

    if d.remote_version and version_gt(d.remote_version, pkg_ver):
        print(f"OK: на GitHub v{d.remote_version} — у exe v{pkg_ver} появится «Обновить»")

    if d.errors:
        return 1
    if not d.download_reachable and d.remote_version:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

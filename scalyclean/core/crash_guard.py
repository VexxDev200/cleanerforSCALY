import sys
import threading
import traceback
from tkinter import messagebox


def install_crash_guard() -> None:
    def hook(exctype, value, tb):
        if issubclass(exctype, KeyboardInterrupt):
            sys.__excepthook__(exctype, value, tb)
            return
        text = "".join(traceback.format_exception(exctype, value, tb))
        try:
            with open("scalyclean_crash.log", "a", encoding="utf-8") as f:
                f.write("\n---\n")
                f.write(text)
        except OSError:
            pass
        try:
            messagebox.showerror("SCALY — ошибка", text[:2000])
        except Exception:
            pass
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = hook

    def thread_hook(args):
        if args.exc_type is SystemExit:
            code = args.exc_value.code if isinstance(args.exc_value, SystemExit) else 0
            if code in (0, None):
                return
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = thread_hook  # type: ignore[attr-defined]

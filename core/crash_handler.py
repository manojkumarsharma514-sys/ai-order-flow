"""
core/crash_handler.py

Catches any exception that would otherwise crash the app silently
behind a --windowed build (no console = no visible traceback = the app
just vanishes with zero explanation to the user). Installs a global
sys.excepthook that:

  1. Writes the full traceback to a rotating log file under
     runtime_paths.LOGS_DIR (so you can ask a user to send you the file)
  2. Shows a plain-language QMessageBox so the user isn't staring at a
     dead app with no idea what happened

Use install() once, right after QApplication is created in app.py.
"""

import sys
import traceback
from datetime import datetime

from PyQt6.QtWidgets import QApplication, QMessageBox

from core.runtime_paths import LOGS_DIR

MAX_LOG_BYTES = 2 * 1024 * 1024  # rotate past 2MB so logs don't grow forever


def _log_path():
    return LOGS_DIR / "crash.log"


def _rotate_if_needed():
    path = _log_path()
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        backup = LOGS_DIR / "crash.log.1"
        try:
            if backup.exists():
                backup.unlink()
            path.rename(backup)
        except OSError:
            pass


def _write_log(exc_type, exc_value, exc_tb) -> str:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed()

    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = f"\n{'=' * 70}\n[{timestamp}] Uncaught exception\n{'=' * 70}\n{text}"

    path = _log_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass  # even if we can't write the log, still show the dialog below

    return str(path)


def _show_dialog(exc_type, exc_value, log_path: str):
    app = QApplication.instance()
    if app is None:
        # No Qt event loop available (crash happened before QApplication
        # was constructed) — nothing to show a dialog in; the log file
        # write above is the only record in that case.
        return

    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("AI OrderFlow Pro — Unexpected Error")
    box.setText(
        "Something went wrong and the application needs to close.\n\n"
        f"Error: {exc_type.__name__}: {exc_value}"
    )
    box.setInformativeText(
        "A detailed error log has been saved. If this keeps happening, "
        "please send that log file for troubleshooting."
    )
    box.setDetailedText(f"Log file:\n{log_path}")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _handle_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        # let Ctrl+C behave normally instead of popping a dialog
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    log_path = _write_log(exc_type, exc_value, exc_tb)

    # also print to stderr — harmless no-op under --windowed (no console
    # to receive it), useful during `python app.py` development
    traceback.print_exception(exc_type, exc_value, exc_tb)

    _show_dialog(exc_type, exc_value, log_path)


def install():
    """Call once, immediately after QApplication(...) is constructed."""
    sys.excepthook = _handle_exception

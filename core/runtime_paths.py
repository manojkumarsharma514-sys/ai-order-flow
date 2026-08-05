"""
core/runtime_paths.py

Your code currently does things like:

    Path("config") / "settings.json"
    Path("data") / "trade_journal.csv"

which works fine when run as `python app.py` (relative to the current
working directory), but breaks in two ways once frozen with PyInstaller:

  1. A frozen app's "current working directory" is NOT guaranteed to be
     the folder the .exe lives in (depends on how the user launches it —
     desktop shortcut, double-click, etc.), so relative paths silently
     resolve to the wrong place or fail to create files at all.

  2. Anything bundled via --add-data is extracted into a temporary,
     READ-ONLY-in-spirit location (`sys._MEIPASS` for --onefile, or the
     app's own install folder for --onedir). Writing trade_journal.csv,
     orders_history.csv, settings.json, or app_state.json into that
     folder is fragile (no write permission in Program Files, and
     everything vanishes on the next --onefile launch anyway).

This module fixes both by giving you two clearly separated roots:

    BASE_DIR   — read-only bundled resources (assets, template config)
    USER_DIR   — writable per-user folder for config/data/logs that
                 persists across app updates and restarts

Drop-in usage — replace `Path("config")` with `runtime_paths.CONFIG_DIR`
and `Path("data")` with `runtime_paths.DATA_DIR` wherever they appear
(core/config.py, core/app_state.py, trading/orders.py, trading/journal.py,
strategy/analytics.py, trading/executor.py, ui/statusbar.py's logo path).
"""

import shutil
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _bundle_base_dir() -> Path:
    """Where bundled READ-ONLY resources live (assets/, config templates).
    In dev this is just the repo root."""

    if _is_frozen():
        # PyInstaller sets sys._MEIPASS for --onefile (temp extraction
        # dir) and it's also valid for --onedir (points at the exe's
        # own folder in that mode).
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

    return Path(__file__).resolve().parent.parent


def _user_data_dir() -> Path:
    """Where the app is allowed to WRITE: settings, app state, CSV
    history, logs. Lives outside the install folder so it survives
    reinstalls/updates and never needs admin/write permission to
    Program Files.

    Windows : %APPDATA%\\AI OrderFlow Pro
    macOS   : ~/Library/Application Support/AI OrderFlow Pro
    Linux   : ~/.local/share/AI OrderFlow Pro

    In dev (not frozen), this resolves to the repo root itself, so
    `python app.py` behaves exactly as it does today — no behavior
    change for local development.
    """

    if not _is_frozen():
        return Path(__file__).resolve().parent.parent

    if sys.platform == "win32":
        import os
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "AI OrderFlow Pro"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AI OrderFlow Pro"
    else:
        return Path.home() / ".local" / "share" / "AI OrderFlow Pro"


BASE_DIR = _bundle_base_dir()
USER_DIR = _user_data_dir()

CONFIG_DIR = USER_DIR / "config"
DATA_DIR = USER_DIR / "data"
LOGS_DIR = USER_DIR / "logs"
ASSETS_DIR = BASE_DIR / "assets"


def ensure_user_data_dir() -> None:
    """
    Call once at app startup (see app.py). Creates the writable
    USER_DIR tree and — on first run only — seeds config/settings.json
    and config/theme.json from the bundled templates shipped under
    BASE_DIR/config_template, so a fresh install starts with your
    shipped defaults instead of core/config.py's hardcoded fallback.
    Never overwrites a config file the user has already saved to.
    """

    for d in (CONFIG_DIR, DATA_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    template_dir = BASE_DIR / "config_template"
    if template_dir.exists():
        for template_file in template_dir.glob("*.json"):
            dest = CONFIG_DIR / template_file.name
            if not dest.exists():
                try:
                    shutil.copy(template_file, dest)
                    print(f"🪄 Seeded default config: {dest}")
                except Exception as e:
                    print(f"⚠️ Could not seed {dest.name}: {e}")

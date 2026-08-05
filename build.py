"""
build.py

One-command PyInstaller build for AI OrderFlow Pro.

Usage:
    python build.py

Produces:
    dist/AI_OrderFlow_Pro/AI_OrderFlow_Pro.exe   (folder build — recommended)

Why a --onedir build instead of --onefile:
    PyQt6 + PyQt6-WebEngine is large (~200-300MB) and --onefile re-extracts
    the whole payload to a temp folder on every launch, which is slow and
    trips antivirus heuristics far more than a plain folder. --onedir
    starts instantly and is what most production PyQt apps ship. If you
    specifically need a single .exe for distribution, see the ONEFILE
    flag below — the script supports both from one place.

This script does NOT hand-edit a .spec file for day-to-day builds; it
calls PyInstaller's Python API directly so all the bundling logic lives
in one version-controlled file. An equivalent .spec is generated
automatically as build/AI_OrderFlow_Pro.spec if you ever want to hand-tune it.
"""

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------

APP_NAME = "AI_OrderFlow_Pro"
ENTRY_POINT = "app.py"          # your existing entry point
ICON_PATH = "assets/icon.ico"   # optional — create one if you want a custom icon

# Set True to produce a single .exe instead of a folder (slower startup,
# easier to email/share as one file).
ONEFILE = False

ROOT = Path(__file__).resolve().parent


# --------------------------------------------------------------------
# Data files / folders that must ship alongside the code.
#
# PyInstaller's --add-data syntax is "SRC<sep>DEST_IN_BUNDLE" where
# <sep> is ';' on Windows and ':' on macOS/Linux. We build the list
# programmatically so it works from either OS.
# --------------------------------------------------------------------

def _sep():
    return ";" if os.name == "nt" else ":"


def _add_data_args():
    """
    Bundles (as READ-ONLY template data, extracted at runtime into
    _MEIPASS — see runtime_paths.py for how the app finds them):

      - assets/            icons, logo images (ui/statusbar.py loads
                            assets/images/delta_logo.png)
      - config/*.json       default settings.json / theme.json — shipped
                            as *templates*; the running app copies them
                            out to a writable per-user folder on first
                            run (see runtime_paths.ensure_user_data_dir)
      - database/           any bundled schema/template files, if present

    NOTE: data/ (CSVs: orders_history, trade_journal, analytics_summary,
    auto_trades_log) is deliberately NOT bundled here — it's runtime
    output, not a template, and must live in a writable location (see
    runtime_paths.py), never inside the read-only frozen bundle.
    """

    sep = _sep()
    args = []

    candidates = [
        ("assets", "assets"),
        ("config", "config_template"),   # renamed on purpose, see note below
        ("database", "database"),
    ]

    for src, dest in candidates:
        src_path = ROOT / src
        if src_path.exists():
            args += ["--add-data", f"{src_path}{sep}{dest}"]
        else:
            print(f"⚠️  Skipping missing data folder: {src_path}")

    return args


# --------------------------------------------------------------------
# Hidden imports
#
# PyInstaller's static analysis misses these because they're either
# imported lazily/conditionally in your code, or pulled in dynamically
# by a package's own plugin system.
# --------------------------------------------------------------------

HIDDEN_IMPORTS = [
    # PyQt6 submodules used indirectly (WebEngine is imported inside a
    # try/except in app.py and ui/chart.py / ui/tv_chart_view.py —
    # PyInstaller's static scan can miss conditionally-imported modules)
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.sip",

    # websockets' asyncio-based internals are dynamically resolved
    "websockets.legacy.client",
    "websockets.legacy.protocol",

    # pandas' CSV engine + a couple of optional-at-runtime submodules
    # that PyInstaller's hook sometimes misses depending on version
    "pandas._libs.tslibs.base",

    # requests' certificate bundle resolution
    "certifi",

    # your own dynamically-touched modules (imported by string / lazy
    # import patterns aren't present in this codebase today, but if you
    # add plugin-style loading later, list those module paths here)
]

# --------------------------------------------------------------------
# Modules to explicitly exclude — trims build size, and avoids pulling
# in test/dev-only frameworks that occasionally confuse PyInstaller's
# dependency walker.
# --------------------------------------------------------------------

EXCLUDES = [
    "tkinter",
    "matplotlib",
    "pytest",
]


def main():
    if not (ROOT / ENTRY_POINT).exists():
        print(f"❌ {ENTRY_POINT} not found in {ROOT}. Run this from the repo root.")
        sys.exit(1)

    # Clean previous builds so stale bundled data files never linger
    for folder in ("build", "dist"):
        p = ROOT / folder
        if p.exists():
            print(f"🧹 Removing old {folder}/ ...")
            shutil.rmtree(p)

    args = [
        ENTRY_POINT,
        f"--name={APP_NAME}",
        "--windowed",       # no console window (equiv. --noconsole)
        "--noconfirm",
        "--clean",
        "--onefile" if ONEFILE else "--onedir",
    ]

    if (ROOT / ICON_PATH).exists():
        args.append(f"--icon={ROOT / ICON_PATH}")
    else:
        print(f"ℹ️  No icon at {ICON_PATH} — building with default PyInstaller icon.")

    args += _add_data_args()

    for hi in HIDDEN_IMPORTS:
        args += ["--hidden-import", hi]

    for ex in EXCLUDES:
        args += ["--exclude-module", ex]

    print("🚀 Running PyInstaller with args:")
    for a in args:
        print("   ", a)

    PyInstaller.__main__.run(args)

    dist_dir = ROOT / "dist" / APP_NAME if not ONEFILE else ROOT / "dist"
    print("\n✅ Build complete.")
    print(f"   Output: {dist_dir}")
    print("   Distribute the ENTIRE folder (not just the .exe) if using --onedir.")


if __name__ == "__main__":
    main()

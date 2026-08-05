# Packaging AI OrderFlow Pro as a Standalone Desktop App

## 0. One-time code changes (do these first)

1. Add `core/runtime_paths.py` and `core/crash_handler.py` (provided).
2. Apply the one-line path swaps listed in the table above to:
   `core/config.py`, `core/app_state.py`, `trading/orders.py`,
   `trading/journal.py`, `strategy/analytics.py`, `trading/executor.py`,
   `ui/statusbar.py`.
3. Replace `app.py` with the patched version (calls
   `ensure_user_data_dir()` and `install_crash_handler()`).
4. Add `build.py` to the repo root.
5. Optional: drop a `.ico` file at `assets/icon.ico` for a custom taskbar/exe icon.

## 1. Set up a clean build environment

Use a **fresh virtual environment** — building from an environment with
extra packages installed bloats the exe and can pull in unrelated
hidden imports.

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

## 2. Test locally before compiling

```cmd
launch.bat
```

Confirm the app opens, connects, and the tabs (Positions/Orders/Journal/
Analytics/Settings) work. Then test the silent path:

```cmd
launch.vbs
```

(double-click it in Explorer — no console should appear).

## 3. Build the executable

```cmd
python build.py
```

This produces:

```
dist/AI_OrderFlow_Pro/
├── AI_OrderFlow_Pro.exe
├── _internal/            (PyQt6, dependencies, bundled assets/config templates)
└── ...
```

Distribute the **entire `AI_OrderFlow_Pro` folder**, not just the `.exe`
— PyInstaller's `--onedir` mode needs the sibling files next to it. Zip
the folder for distribution, or use step 5 below for a proper installer.

If you set `ONEFILE = True` in `build.py`, you instead get a single
`dist/AI_OrderFlow_Pro.exe` — simpler to share, but slower to start
since it self-extracts to a temp folder on every launch.

## 4. Verify the build

Run the exe **from a different folder** than the source repo (e.g. copy
`dist/AI_OrderFlow_Pro/` to your Desktop first) to catch any
still-hardcoded relative path:

```cmd
cd %USERPROFILE%\Desktop\AI_OrderFlow_Pro
AI_OrderFlow_Pro.exe
```

Check:
- No console window appears.
- The Delta logo renders in the footer (confirms `assets/` bundled correctly).
- Settings tab → Save Settings, close, reopen — confirms it's writing
  to `%APPDATA%\AI OrderFlow Pro\config\settings.json`, not failing
  silently inside the read-only bundle.
- Force a crash (e.g. temporarily raise an exception in `refresh_ui`) to
  confirm the QMessageBox + `%APPDATA%\AI OrderFlow Pro\logs\crash.log`
  both appear correctly, then revert.

## 5. (Optional) Build a real Windows installer

A zipped folder works, but a proper installer is friendlier for
non-technical end users. **Inno Setup** (free) is the standard choice:

1. Install [Inno Setup](https://jrsoftware.org/isinfo.php).
2. Create `installer.iss`:

```ini
[Setup]
AppName=AI OrderFlow Pro
AppVersion=1.0.0
DefaultDirName={autopf}\AI OrderFlow Pro
DefaultGroupName=AI OrderFlow Pro
OutputDir=installer_output
OutputBaseFilename=AI_OrderFlow_Pro_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\AI_OrderFlow_Pro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\AI OrderFlow Pro"; Filename: "{app}\AI_OrderFlow_Pro.exe"
Name: "{autodesktop}\AI OrderFlow Pro"; Filename: "{app}\AI_OrderFlow_Pro.exe"

[Run]
Filename: "{app}\AI_OrderFlow_Pro.exe"; Description: "Launch AI OrderFlow Pro"; Flags: nowait postinstall skipifsilent
```

3. Compile it with the Inno Setup Compiler → produces
   `installer_output\AI_OrderFlow_Pro_Setup.exe`, a standard Windows
   installer with Start Menu + Desktop shortcuts and an uninstaller.

## 6. Common pitfalls checklist

| Symptom | Cause | Fix |
|---|---|---|
| App works via `python app.py` but crashes silently as .exe | Relative `Path("config")`/`Path("data")` writing into a read-only bundle location | Apply the `runtime_paths` swap (step 0) |
| Logo/images missing in the exe | `assets/` not passed via `--add-data` | Confirm `assets/` exists at repo root before running `build.py` |
| "Failed to load PyQt6 platform plugin" on a clean machine | Qt plugin DLLs excluded by an overly aggressive `--exclude-module` | Remove any excludes touching `PyQt6.*` |
| Antivirus flags the .exe | Common false-positive with PyInstaller `--onefile` | Prefer `--onedir` (default in `build.py`), or code-sign the exe |
| WebEngine tab shows "package not installed" in the built exe even though it worked in dev | `PyQt6-WebEngine` wasn't in the venv used to build | `pip install PyQt6-WebEngine` in the build venv before running `build.py` |

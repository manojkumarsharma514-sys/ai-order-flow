@echo off
REM launch.bat
REM
REM Local dev launcher — keeps a console window open so you can see
REM print()/error output while testing. This is what you'd use WHILE
REM developing, not what end users double-click.
REM
REM For a silent, no-console launch (closer to what the final .exe
REM will feel like), use launch.vbs instead.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found at venv\. Create one first:
    echo.
    echo     python -m venv venv
    echo     venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

venv\Scripts\python.exe app.py

if errorlevel 1 (
    echo.
    echo App exited with an error. See above ^(or logs\crash.log^).
    pause
)

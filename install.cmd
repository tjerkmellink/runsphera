@echo off
REM RunSphera installer / repair.
REM
REM Run this ONCE (double-click). It sets up the Python environment and creates
REM "RunSphera" shortcuts on your Desktop and Start Menu. After that, launch the
REM app from a shortcut (pin it to the taskbar) - not from this file.
REM
REM Re-running install.cmd repairs a broken environment and refreshes the
REM shortcuts, then launches the app.
setlocal
cd /d "%~dp0"

echo ============================================================
echo   RunSphera - setup
echo ============================================================
echo.

REM ---- Health check: venv present and key packages importable? ----
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, jinja2, webview" >nul 2>&1
    if not errorlevel 1 goto shortcuts
)

REM ---- Find a Python 3 interpreter (py launcher first, then PATH) ----
set "PYTHON="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3"
if not defined PYTHON (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    echo Python 3.12 or newer was not found on this computer.
    echo.
    echo Install it from https://www.python.org/downloads/ and make sure
    echo "Add python.exe to PATH" is ticked during setup, then run
    echo install.cmd again.
    echo.
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
%PYTHON% -m venv .venv
if errorlevel 1 goto setup_failed

echo [2/3] Installing dependencies ^(this can take a few minutes^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

:shortcuts
echo [3/3] Creating RunSphera shortcuts ^(Desktop + Start Menu^)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\install_shortcut.ps1"
if errorlevel 1 echo    ^(Could not create shortcuts - you can still launch with pythonw -m runsphera.desktop.^)

echo.
echo ============================================================
echo   RunSphera is ready.
echo ============================================================
echo   * A "RunSphera" shortcut is on your Desktop and in the Start Menu.
echo   * Right-click it and choose "Pin to taskbar" to keep it handy.
echo   * From now on, launch RunSphera from that shortcut - not this file.
echo.
echo   Starting RunSphera...

start "" ".venv\Scripts\pythonw.exe" -m runsphera.desktop
exit /b 0

:setup_failed
echo.
echo Setup failed - see the messages above for details.
echo Fix the problem and run install.cmd again.
pause
exit /b 1

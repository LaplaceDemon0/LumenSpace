@echo off
title LumenSpace
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
python --version >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    if errorlevel 1 goto error
    goto install
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    if errorlevel 1 goto error
    goto install
)
echo Python was not found. Install Python 3.12 with "Add python.exe to PATH" enabled.
pause
exit /b 1
:install
rem Reinstall on every launch so project updates also install new dependencies.
".venv\Scripts\python.exe" -m pip install -e ".[topology,mt5]"
if errorlevel 1 goto error
".venv\Scripts\python.exe" run.py
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo Setup or startup failed. See the error above.
pause
exit /b 1

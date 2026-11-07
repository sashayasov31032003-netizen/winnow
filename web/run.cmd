@echo off
rem Winnow web app. Works from any directory.
setlocal
cd /d "%~dp0.."

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Environment not found. Run in the project folder:
    echo   python -m venv --system-site-packages web\.venv
    echo   web\.venv\Scripts\python -m pip install -r web\requirements.txt
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%\src"
"%~dp0.venv\Scripts\python.exe" -m winnow.web
if errorlevel 1 pause

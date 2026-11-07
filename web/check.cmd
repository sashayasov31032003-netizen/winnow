@echo off
rem Full self-check of the Winnow web app on real data files.
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
"%~dp0.venv\Scripts\python.exe" web\selfcheck.py %*
pause

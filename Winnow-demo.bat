@echo off
rem Демонстрационный анализ в консоли: работает без PySide6, только numpy/pandas/scipy.
title Winnow - демо
cd /d "%~dp0"
python "%~dp0run.py" demo
echo.
pause >nul

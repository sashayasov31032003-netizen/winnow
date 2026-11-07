@echo off
rem Запуск Winnow двойным щелчком: окно консоли не закрывается, поэтому любую
rem ошибку видно. run.py сам подбирает интерпретатор, в котором есть PySide6.
title Winnow
cd /d "%~dp0"
python "%~dp0run.py" %*
echo.
echo Winnow завершён. Нажмите любую клавишу, чтобы закрыть окно.
pause >nul

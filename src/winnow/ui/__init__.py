"""Графический интерфейс Winnow (PySide6).

Импорт Qt здесь намеренно отложенный: пакет ``winnow.ui`` содержит также
описания окон процедур (procedure_specs), которые не зависят от Qt и должны
импортироваться даже там, где PySide6 не установлен. Иначе проверка ядра
становится невозможной без установки GUI.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MainWindow"]


def __getattr__(name: str) -> Any:
    """Ленивая загрузка MainWindow: Qt подключается только при обращении."""
    if name == "MainWindow":
        from winnow.ui.main_window import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

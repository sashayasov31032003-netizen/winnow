"""Подбор шрифта интерфейса.

Зачем это отдельный модуль: Qt перестал поставлять шрифты, и в некоторых
режимах (например, безэкранном) список доступных семейств вообще пуст. Тогда
весь текст рисуется пустыми прямоугольниками - интерфейс формально работает, но
выглядит сломанным. Здесь мы это проверяем и при необходимости подгружаем
системный шрифт из файла.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# Порядок предпочтения: сначала системные шрифты Windows, затем запасные.
_UI_PREFERENCES = ("Segoe UI", "Segoe UI Variable", "Tahoma", "Arial", "DejaVu Sans")
_MONO_PREFERENCES = ("Consolas", "Cascadia Mono", "Courier New", "DejaVu Sans Mono")

# Файлы, которыми можно наполнить пустую библиотеку шрифтов.
_FALLBACK_FILES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"/System/Library/Fonts/Helvetica.ttc",
)

_loaded = False


def ensure_fonts_loaded(force: bool = False) -> list[str]:
    """Гарантирует, что в Qt есть хотя бы один шрифт.

    Возвращает список семейств, которые удалось загрузить. При обычном запуске
    ничего не делает: библиотека шрифтов уже заполнена системой.
    """
    global _loaded
    if _loaded and not force:
        return []

    families = QFontDatabase.families()
    if families:
        _loaded = True
        return []

    loaded_families: list[str] = []
    for path in _FALLBACK_FILES:
        if not Path(path).exists():
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id != -1:
            loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id))

    _loaded = True
    return loaded_families


def pick_ui_font(preferences: tuple[str, ...] = _UI_PREFERENCES) -> str:
    """Выбирает первое доступное семейство из списка предпочтений.

    Если ничего не найдено, возвращает первое доступное семейство вообще, а при
    полностью пустой библиотеке - первое предпочтение (шрифт подставит система).
    """
    available = set(QFontDatabase.families())
    for name in preferences:
        if name in available:
            return name
    if available:
        return sorted(available)[0]
    return preferences[0]


def ui_font_point_size(default: int = 10) -> int:
    """Размер шрифта по умолчанию, приведённый к разумным границам."""
    size = QApplication.font().pointSize() if QApplication.instance() else default
    if size <= 0:
        return default
    return max(8, min(14, size))


def apply_base_font(app: QApplication, point_size: int | None = None) -> QFont:
    """Устанавливает базовый шрифт приложения. Возвращает выбранный шрифт."""
    ensure_fonts_loaded()
    family = pick_ui_font()
    font = QFont(family)
    font.setPointSize(point_size or ui_font_point_size())
    app.setFont(font)
    return font


__all__ = [
    "apply_base_font",
    "ensure_fonts_loaded",
    "pick_ui_font",
    "ui_font_point_size",
]

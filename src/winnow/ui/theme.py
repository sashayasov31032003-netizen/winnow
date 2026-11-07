"""Дизайн-токены Winnow: цвета, шрифты, отступы, радиусы.

Смысл этого модуля - единый источник правды для внешнего вида. Пока значений
немного, соблазн писать цвета прямо в виджетах велик, но тогда через двадцать
виджетов интерфейс начнёт «разъезжаться»: три разных оттенка серого, четыре
размера отступа. Поэтому все значения живут здесь, а виджеты их только берут.

Палитра сознательно сдержанная: один акцентный цвет, нейтральная серая шкала и
семантические цвета для статусов. Цвет должен нести смысл, а не украшать -
статистический пакет выглядит спокойно.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Palette:
    """Набор цветов одной темы."""

    name: str
    is_dark: bool

    # Фоны: от самого внешнего до самого вложенного.
    canvas: str          # фон рабочей области
    surface: str         # фон панелей и карточек
    surface_alt: str     # чередование строк, второстепенные панели
    surface_sunken: str  # поля ввода, «утопленные» области

    # Границы.
    border: str
    border_strong: str

    # Текст.
    text: str            # основной
    text_muted: str      # второстепенный: подписи, подсказки
    text_disabled: str
    text_on_accent: str  # текст поверх акцентного цвета

    # Акцент.
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str     # очень светлый акцентный фон: выделение строки

    # Семантика: предупреждения и подсветка пропусков.
    success: str
    warning: str
    danger: str
    warning_soft: str
    danger_soft: str


LIGHT = Palette(
    name="Светлая",
    is_dark=False,
    canvas="#f1f4f8",
    surface="#ffffff",
    surface_alt="#f8fafc",
    surface_sunken="#eef2f7",
    border="#dbe2ea",
    border_strong="#c3cdd9",
    text="#16212e",
    text_muted="#63748a",
    text_disabled="#a3b0bf",
    text_on_accent="#ffffff",
    accent="#1f6fd0",
    accent_hover="#1a60b6",
    accent_pressed="#155099",
    accent_soft="#e8f1fc",
    success="#1f8a52",
    warning="#b8760c",
    danger="#c0392b",
    warning_soft="#fdf3e2",
    danger_soft="#fdecea",
)

DARK = Palette(
    name="Тёмная",
    is_dark=True,
    canvas="#14181d",
    surface="#1c2229",
    surface_alt="#222932",
    surface_sunken="#11151a",
    border="#2e3844",
    border_strong="#3d4a58",
    text="#e7edf4",
    text_muted="#94a3b5",
    text_disabled="#5c6a7a",
    text_on_accent="#ffffff",
    accent="#4c9aeb",
    accent_hover="#61a9f0",
    accent_pressed="#3a86d6",
    accent_soft="#1b3a52",
    success="#3fbd77",
    warning="#e0a33c",
    danger="#ef6b5e",
    warning_soft="#3a2f19",
    danger_soft="#3d2222",
)

THEMES: dict[str, Palette] = {"light": LIGHT, "dark": DARK}

# Цвета для серий данных: категории на столбчатой и круговой диаграмме, линии
# на графике рассеяния. Подобраны так, чтобы соседние цвета различались и на
# светлой, и на тёмной теме, и чтобы график читался при печати в оттенках серого.
SERIES_COLORS: tuple[str, ...] = (
    "#1f6fd0",
    "#e8871a",
    "#2f9e6b",
    "#c2453f",
    "#7b5bb5",
    "#0f8b9e",
    "#c9a227",
    "#5a6b7d",
)


def series_color(index: int) -> str:
    """Цвет серии по её номеру: цвета повторяются по кругу."""
    return SERIES_COLORS[index % len(SERIES_COLORS)]


@dataclass(frozen=True)
class Spacing:
    """Шкала отступов. Кратность 4 пунктам - привычный и предсказуемый ритм."""

    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(frozen=True)
class Radii:
    sm: int = 4
    md: int = 6
    lg: int = 10
    pill: int = 999


@dataclass(frozen=True)
class Typography:
    """Шрифты и размеры.

    Для интерфейса берётся системный шрифт: он лучше отрисован и не требует
    поставки своих файлов. Для чисел и синтаксиса - моноширинный, чтобы столбцы
    таблиц выравнивались.
    """

    family: str = "Segoe UI"
    family_mono: str = "Consolas"
    size_small: int = 11
    size_base: int = 12
    size_medium: int = 13
    size_large: int = 16
    size_title: int = 22

    def pt(self, size: int) -> str:
        return f"{size}pt"


@dataclass(frozen=True)
class DesignSystem:
    """Полная система оформления: палитра плюс геометрия плюс типографика."""

    palette: Palette
    spacing: Spacing = field(default_factory=Spacing)
    radii: Radii = field(default_factory=Radii)
    typography: Typography = field(default_factory=Typography)


def design_system(theme: str = "light") -> DesignSystem:
    """Возвращает систему оформления для темы "light" или "dark"."""
    try:
        palette = THEMES[theme]
    except KeyError:
        raise ValueError(
            f"Неизвестная тема: {theme!r}. Доступны: {', '.join(THEMES)}"
        ) from None
    return DesignSystem(palette=palette)


def qt_palette(theme: str = "light"):
    """Собирает палитру Qt из токенов темы.

    Нужна дополнительно к таблице стилей: часть внутренних элементов Qt
    (область прокрутки диалога, вьюпорт, подсказки) берёт цвет не из стилей, а
    из палитры. Без этого в тёмной теме остаются крупные светло-серые участки -
    ровно то, что выглядит как «недокрашенное» окно.
    """
    from PySide6.QtGui import QColor, QPalette

    p = THEMES.get(theme)
    if p is None:
        raise ValueError(f"Неизвестная тема: {theme!r}")

    palette = QPalette()
    mapping = {
        QPalette.ColorRole.Window: p.canvas,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface_sunken,
        QPalette.ColorRole.AlternateBase: p.surface_alt,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.PlaceholderText: p.text_muted,
        QPalette.ColorRole.Button: p.surface_alt,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.BrightText: p.danger,
        QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.text_on_accent,
        QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.Link: p.accent,
        QPalette.ColorRole.Mid: p.border,
        QPalette.ColorRole.Dark: p.border_strong,
        QPalette.ColorRole.Shadow: p.border_strong,
    }
    for role, color in mapping.items():
        palette.setColor(role, QColor(color))

    # Отключённые элементы: иначе они остаются системно-серыми и выбиваются.
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(p.text_disabled)
        )
    return palette

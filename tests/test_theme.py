"""Тесты дизайн-системы и оформления.

Смысл: внешний вид легко «разъезжается» незаметно — появляется третий оттенок
серого или отступ, не кратный шкале. Эти проверки держат систему в согласии и
не требуют заглядывать в скриншоты после каждой правки.
"""

from __future__ import annotations

import re

import pytest

from winnow.ui.theme import DARK, LIGHT, THEMES, design_system


@pytest.fixture(scope="module")
def qt_app():
    """Приложение Qt нужно для операций с пиксмапами и иконками.

    Без него получение пиксмапа из иконки аварийно завершает процесс, а не
    бросает исключение - поэтому фикстура обязательна, а не «на всякий случай».
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_both_themes_registered():
    assert set(THEMES) == {"light", "dark"}
    assert THEMES["light"] is LIGHT
    assert THEMES["dark"] is DARK


def test_app_icon_has_all_needed_sizes(qt_app):
    """Значок программы должен содержать все размеры, которые просит Windows.

    Без этого в панели задач появляется размытая картинка, увеличенная из
    маленькой, а значок ярлыка выглядит хуже остальных.
    """
    from winnow.ui.icons import LOGO_SIZES, app_icon

    icon = app_icon()
    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    for size in (16, 32, 48, 256):
        assert size in sizes, f"в значке нет размера {size}"
    assert min(LOGO_SIZES) >= 16
    assert max(LOGO_SIZES) >= 256


def test_logo_is_drawn_and_not_empty(qt_app):
    """Значок рисуется кодом: он обязан быть непрозрачным и цветным.

    Пустой или полностью прозрачный значок означал бы, что рисование сломали, а
    заметно это было бы только в проводнике.
    """
    from winnow.ui.icons import logo_pixmap

    pixmap = logo_pixmap(64)
    assert pixmap.width() == 64 and pixmap.height() == 64
    image = pixmap.toImage()
    assert image.hasAlphaChannel()
    # Считаем непрозрачные точки: их должна быть заметная часть квадрата.
    opaque = 0
    for y in range(0, 64, 4):
        for x in range(0, 64, 4):
            if image.pixelColor(x, y).alpha() > 200:
                opaque += 1
    total = len(range(0, 64, 4)) ** 2
    assert opaque > total * 0.5, "значок почти пустой"


def test_unknown_theme_is_reported():
    with pytest.raises(ValueError) as error:
        design_system("neon")
    assert "neon" in str(error.value)


def test_themes_have_all_colors_set():
    """Ни один цвет не должен остаться пустым: иначе виджет окажется невидимым."""
    from dataclasses import fields

    from winnow.ui.theme import Palette

    for name, palette in THEMES.items():
        for field in fields(Palette):
            if field.name in ("name", "is_dark"):
                continue
            value = getattr(palette, field.name)
            assert value, f"{name}.{field.name} пуст"
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), (
                f"{name}.{field.name} = {value!r} не является цветом вида #rrggbb"
            )


def test_themes_differ_in_lightness():
    """Светлая тема должна быть заметно светлее тёмной."""
    def brightness(color: str) -> int:
        r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
        return r + g + b

    assert brightness(LIGHT.canvas) > brightness(DARK.canvas) + 150
    assert brightness(LIGHT.text) < brightness(LIGHT.canvas)
    assert brightness(DARK.text) > brightness(DARK.canvas)


def test_spacing_scale_is_ordered():
    spacing = design_system().spacing
    values = [
        spacing.xxs, spacing.xs, spacing.sm, spacing.md, spacing.lg, spacing.xl, spacing.xxl
    ]
    assert values == sorted(values)
    assert len(set(values)) == len(values), "шаги шкалы отступов должны различаться"


def test_typography_sizes_are_ordered():
    t = design_system().typography
    sizes = [t.size_small, t.size_base, t.size_medium, t.size_large, t.size_title]
    assert sizes == sorted(sizes)


def test_stylesheet_contains_theme_colors():
    from winnow.ui.styles import stylesheet

    light = stylesheet("light")
    dark = stylesheet("dark")

    assert LIGHT.accent in light
    assert DARK.accent in dark
    assert light != dark
    # Тёмная тема не должна содержать светлых фонов.
    assert LIGHT.canvas not in dark


def test_stylesheet_has_no_unresolved_braces():
    """Ошибка в f-строке оставила бы лишние скобки и сломала оформление."""
    from winnow.ui.styles import stylesheet

    for theme in ("light", "dark"):
        text = stylesheet(theme)
        assert text.count("{") == text.count("}")
        assert "None" not in text


def test_stylesheet_covers_key_widgets():
    from winnow.ui.styles import stylesheet

    text = stylesheet("light")
    for selector in ("QMainWindow", "QMenuBar", "QTableView", "QTabBar::tab",
                     "QPushButton", "QComboBox", "QCheckBox::indicator", "QToolBar"):
        assert selector in text, f"в оформлении нет правил для {selector}"


def test_html_output_css_follows_theme():
    from winnow.export.html import css_from_theme

    light = css_from_theme("light")
    dark = css_from_theme("dark")

    assert LIGHT.text in light
    assert DARK.text in dark
    assert light != dark
    # Заголовки таблиц не должны переноситься по одной букве.
    assert "white-space: nowrap" in light
    assert "border-collapse: collapse" in light


def test_report_html_uses_theme_and_numbering():
    from winnow.export.html import report_to_html
    from winnow.samples import demo_dataset
    from winnow.stats.command import DescriptivesCommand

    dataset = demo_dataset(n=40, seed=3)
    result = DescriptivesCommand(
        dataset=dataset, variables=["age"], statistics=["n", "mean"]
    ).execute()

    html = report_to_html([result], theme="dark")
    assert DARK.text in html
    assert "1. Описательные статистики" in html

    without_title = report_to_html([result], theme="light", show_title=False)
    assert "<h1>" not in without_title


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_icons_are_drawn_for_both_themes(theme, qt_app):
    """Иконки рисуются кодом; проверяем, что они не пустые."""
    from winnow.ui.icons import toolbar_icons

    icons = toolbar_icons(THEMES[theme].text_muted)
    assert set(icons) >= {"open", "bars", "grid", "export"}
    for name, icon in icons.items():
        assert not icon.isNull(), f"иконка {name} пуста"
        pixmap = icon.pixmap(20, 20)
        assert not pixmap.isNull()

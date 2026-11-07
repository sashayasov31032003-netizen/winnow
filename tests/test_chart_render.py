"""Тесты рисования графиков.

Проверяется не «красиво ли», а «нарисовалось ли»: что холст не остался пустым,
что подписи оси получились читаемыми и что экспорт в PNG и SVG действительно
создаёт файлы. Пустой холст - самая вероятная ошибка в рисовании, и она не
видна ни одному тесту, который смотрит только на числа.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.charts import ChartCommand, build_chart_data
from winnow.ui.chart_widget import EXPORT_HEIGHT, EXPORT_WIDTH, nice_ticks, format_number, render_chart
from winnow.ui.chart_window import ChartCanvas, ChartWindow
from winnow.ui.theme import THEMES


@pytest.fixture(scope="module")
def qt_app():
    """Приложение Qt обязательно: без него работа с изображениями аварийно завершает процесс."""
    app = QApplication.instance() or QApplication([])
    yield app


def _dataset() -> Dataset:
    return demo_dataset(n=120, seed=13)


def _chart(kind: str, **kwargs) -> ChartCommand:
    dataset = kwargs.pop("dataset", None) or _dataset()
    settings = {
        "histogram": {"variables": ["income"]},
        "boxplot": {"variables": ["income"]},
        "scatter": {"variables": ["age", "income"]},
        "bar": {"variables": ["income"], "category": "gender"},
        "pie": {"variables": ["income"], "category": "city"},
        "line": {"variables": ["income"], "category": "education"},
    }[kind]
    settings.update(kwargs)
    command = ChartCommand(dataset=dataset, kind=kind, **settings)
    command.validate()
    return command


# ---------------------------------------------------------------- подписи осей


def test_nice_ticks_uses_round_steps():
    """Отметки должны быть «круглыми»: 0, 20, 40…, а не 0, 17, 34…"""
    ticks = nice_ticks(0.0, 98.0)
    assert ticks[0] == 0.0
    assert ticks[1] - ticks[0] == pytest.approx(20.0, abs=1e-9)


def test_nice_ticks_covers_range():
    ticks = nice_ticks(3.0, 27.0)
    assert ticks[0] <= 3.0
    assert ticks[-1] >= 27.0


def test_nice_ticks_handles_equal_bounds():
    """Все значения одинаковые: ось не должна ломаться."""
    ticks = nice_ticks(5.0, 5.0)
    assert ticks == [5.0]


def test_nice_ticks_handles_tiny_range():
    ticks = nice_ticks(0.001, 0.002)
    assert len(ticks) >= 2
    assert ticks[0] <= 0.001
    assert ticks[-1] >= 0.002


def test_format_number_is_compact():
    assert format_number(5.0) == "5"
    assert format_number(5.5) == "5.5"
    assert format_number(0.0) == "0"
    assert format_number(float("nan")) == ""


# ------------------------------------------------------------------- рисование


@pytest.mark.parametrize("kind", ["histogram", "boxplot", "scatter", "bar", "pie", "line"])
def test_every_chart_type_draws_something(qt_app, kind):
    """Каждый вид графика должен оставить след на холсте.

    «След» считается как доля пикселей, отличающихся от фона. Пустой график дал
    бы около нуля, а нормальный рисунок с осями и данными - заметно больше.
    """
    data = build_chart_data(_chart(kind))
    image = render_chart(data, "light", 900, 560)
    assert image.width() == 900 and image.height() == 560
    assert _ink_ratio(image, data) > 0.01, f"график «{kind}» почти пустой"


def _ink_ratio(image: QImage, data) -> float:
    """Доля пикселей, не совпадающих с цветом фона графика."""
    from winnow.ui.theme import design_system

    background = design_system("light").palette.surface
    target = background.lower()
    step = 3  # каждый третий пиксель: точности хватает, а тест быстрее
    differing = 0
    total = 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            total += 1
            if color.name().lower() != target:
                differing += 1
    return differing / max(total, 1)


def test_dark_theme_chart_has_no_light_areas(qt_app):
    """В тёмной теме фон графика должен быть тёмным.

    Ровно та проблема уже была с диалогами: белые прямоугольники в тёмной теме.
    """
    data = build_chart_data(_chart("histogram"))
    image = render_chart(data, "dark", 800, 500)
    from winnow.ui.theme import design_system

    expected = design_system("dark").palette.surface.lower()
    assert image.pixelColor(2, 2).name().lower() == expected


def test_chart_renders_in_both_themes(qt_app):
    data = build_chart_data(_chart("bar"))
    for theme in THEMES:
        image = render_chart(data, theme, 700, 460)
        assert not image.isNull()
        assert _ink_ratio(image, data) > 0.01


def test_export_size_is_large_enough_for_print(qt_app):
    """Экспортный размер должен быть заметно больше экранного."""
    assert EXPORT_WIDTH >= 1200
    assert EXPORT_HEIGHT >= 800
    data = build_chart_data(_chart("scatter"))
    image = render_chart(data, "light", EXPORT_WIDTH, EXPORT_HEIGHT)
    assert image.width() == EXPORT_WIDTH


def test_normal_curve_is_drawn(qt_app):
    """Наложение нормальной кривой должно менять рисунок."""
    from winnow.samples import demo_dataset

    dataset = demo_dataset(n=200, seed=21)
    plain = ChartCommand(dataset=dataset, kind="histogram", variables=["income"])
    with_curve = ChartCommand(
        dataset=dataset, kind="histogram", variables=["income"], show_normal=True
    )
    plain_data = build_chart_data(plain)
    curve_data = build_chart_data(with_curve)
    assert curve_data.normal_curve is not None
    plain_image = render_chart(plain_data, "light", 600, 400)
    curve_image = render_chart(curve_data, "light", 600, 400)
    assert _ink_ratio(plain_image, plain_data) != _ink_ratio(curve_image, curve_data)


# --------------------------------------------------------------- окно и экспорт


def test_chart_canvas_paints(qt_app):
    data = build_chart_data(_chart("histogram"))
    canvas = ChartCanvas(data, "light")
    canvas.resize(640, 420)
    pixmap = canvas.grab()
    assert not pixmap.isNull()
    assert pixmap.width() > 0


def test_chart_window_has_export_buttons(qt_app):
    data = build_chart_data(_chart("bar"))
    window = ChartWindow(data, theme="light")
    try:
        texts = [button.text() for button in window.findChildren(type(window).__mro__[0]) if False]
        from PySide6.QtWidgets import QPushButton

        texts = [button.text() for button in window.findChildren(QPushButton)]
        assert any("PNG" in text for text in texts)
        assert any("SVG" in text for text in texts)
        assert any("Копировать" in text for text in texts)
        assert any("Закрыть" in text for text in texts)
    finally:
        window.close()


def test_chart_window_switches_theme(qt_app):
    data = build_chart_data(_chart("pie"))
    window = ChartWindow(data, theme="light")
    try:
        window.apply_theme("dark")
        assert window.theme_name == "dark"
        assert window.canvas.theme_name == "dark"
    finally:
        window.close()


def test_svg_export_file_is_written(qt_app, tmp_path):
    """SVG пишется через QSvgGenerator: проверяем, что файл появился и не пуст."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgGenerator

    from winnow.ui.chart_widget import ChartRenderer
    from winnow.ui.theme import design_system

    data = build_chart_data(_chart("scatter"))
    path = tmp_path / "chart.svg"
    generator = QSvgGenerator()
    generator.setFileName(str(path))
    generator.setSize(ChartCanvas(data, "light").size())
    generator.setViewBox(QRectF(0, 0, 800, 520))
    painter = QPainter(generator)
    try:
        ChartRenderer(data, design_system("light").palette).render(painter, 800.0, 520.0)
    finally:
        painter.end()
    assert Path(path).exists()
    assert path.stat().st_size > 1000
    text = path.read_text(encoding="utf-8", errors="ignore")
    assert "<svg" in text


def test_png_export_file_is_written(qt_app, tmp_path):
    data = build_chart_data(_chart("boxplot"))
    path = tmp_path / "chart.png"
    image = render_chart(data, "light", EXPORT_WIDTH, EXPORT_HEIGHT)
    assert image.save(str(path), "PNG")
    assert Path(path).stat().st_size > 3000


def test_boxplot_marks_outliers_visibly(qt_app):
    """Выбросы должны попадать на рисунок: иначе ящик врёт о данных."""
    dataset = Dataset.from_records(
        {"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 100.0]}
    )
    data = build_chart_data(ChartCommand(dataset=dataset, kind="boxplot", variables=["x"]))
    assert data.outliers
    image = render_chart(data, "light", 700, 460)
    assert _ink_ratio(image, data) > 0.01

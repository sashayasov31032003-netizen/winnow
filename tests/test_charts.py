"""Тесты расчёта данных для графиков.

Проверяется именно арифметика: интервалы гистограммы, квартили и усы, частоты
категорий, линия регрессии. Рисование проверяется отдельно в интерфейсных тестах,
а здесь важно, что числа под графиком верные - по графику ошибку не увидеть.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from winnow.core.dataset import Dataset
from winnow.samples import demo_dataset
from winnow.stats.charts import (
    ChartCommand,
    box_statistics,
    build_chart_data,
    category_counts,
    chart_caption,
    histogram,
    normal_curve,
    scatter_points,
    sturges_bins,
)
from winnow.stats.command import CommandError


def _dataset() -> Dataset:
    return Dataset.from_records(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
            "y": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
            "group": [1, 1, 2, 2, 2, 3, 3, 3, 3, 3],
        }
    )


# ------------------------------------------------------------- гистограмма


def test_sturges_bins_grows_with_sample_size():
    """Правило Стёрджесса: интервалов больше при большем объёме."""
    assert sturges_bins(4) < sturges_bins(100) < sturges_bins(10000)
    assert sturges_bins(1) == 1
    assert sturges_bins(0) == 1


def test_histogram_counts_sum_to_sample_size():
    """Ключевое свойство: сумма частот равна числу наблюдений."""
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    edges, counts = histogram(values, bins=4)
    assert len(edges) == 5          # на один больше, чем интервалов
    assert len(counts) == 4
    assert int(counts.sum()) == 8


def test_histogram_edges_cover_all_values():
    values = np.array([0.5, 1.5, 2.5, 9.5])
    edges, _counts = histogram(values, bins=3)
    assert edges[0] <= values.min()
    assert edges[-1] >= values.max()


def test_histogram_ignores_missing_values():
    values = np.array([1.0, np.nan, 3.0, np.inf, 5.0])
    edges, counts = histogram(values, bins=2)
    assert int(counts.sum()) == 3


def test_histogram_of_empty_data_is_empty():
    edges, counts = histogram(np.array([]), bins=5)
    assert len(edges) == 0
    assert len(counts) == 0


def test_explicit_bin_count_is_respected():
    values = np.arange(0, 100, 1.0)
    _edges, counts = histogram(values, bins=10)
    assert len(counts) == 10


def test_normal_curve_is_scaled_to_counts():
    """Кривая должна быть в тех же единицах, что и столбцы.

    Если перепутать плотность и частоты, кривая окажется в десятки раз ниже
    столбцов, и наложение потеряет смысл.
    """
    generator = np.random.default_rng(9)
    values = generator.normal(0, 1, 500)
    edges, counts = histogram(values, bins=12)
    xs, ys = normal_curve(values, len(counts))
    assert len(xs) == len(ys) == 80
    # Максимум кривой должен быть сопоставим с высотой столбцов.
    assert 0.2 * max(counts) < max(ys) < 3.0 * max(counts)


def test_normal_curve_needs_variation():
    """Без разброса кривую построить нельзя: деление на ноль."""
    xs, ys = normal_curve(np.array([5.0, 5.0, 5.0]), 2)
    assert xs == [] and ys == []


# ------------------------------------------------------------ ящик с усами


def test_box_statistics_quartiles_are_correct():
    """Квартили на данных 1..10: Q1 = 3.25, медиана = 5.5, Q3 = 7.75."""
    data = np.arange(1.0, 11.0)
    box = box_statistics(data)
    assert box["q1"] == pytest.approx(3.25, abs=1e-9)
    assert box["median"] == pytest.approx(5.5, abs=1e-9)
    assert box["q3"] == pytest.approx(7.75, abs=1e-9)
    assert box["iqr"] == pytest.approx(4.5, abs=1e-9)


def test_box_statistics_finds_outliers_by_fence_rule():
    """Выброс - значение за пределами 1.5 межквартильных размаха."""
    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0])
    box = box_statistics(data)
    assert 100.0 in box["outliers"]
    assert box["upper_whisker"] < 100.0
    # Выброс не должен раздувать ус: ус заканчивается на последнем обычном значении.
    assert box["upper_whisker"] <= box["maximum"]


def test_box_statistics_whiskers_cover_inside_values():
    data = np.arange(1.0, 21.0)
    box = box_statistics(data)
    assert box["lower_whisker"] == pytest.approx(1.0)
    assert box["upper_whisker"] == pytest.approx(20.0)
    assert box["outliers"] == []


def test_box_statistics_reports_sample_size_and_mean():
    data = np.array([1.0, 2.0, 3.0, 4.0])
    box = box_statistics(data)
    assert box["n"] == 4
    assert box["mean"] == pytest.approx(2.5, abs=1e-9)


# ------------------------------------------------------------- категории


def test_category_counts_preserve_appearance_order():
    import pandas as pd

    labels = pd.Series(["Москва", "Другой", "Москва", "Тверь", "Другой", "Москва"])
    categories, counts = category_counts(labels)
    assert categories == ["Москва", "Другой", "Тверь"]
    assert counts == [3, 2, 1]
    assert sum(counts) == len(labels)


def test_scatter_points_drop_incomplete_pairs():
    import pandas as pd

    x = pd.Series([1.0, 2.0, np.nan, 4.0])
    y = pd.Series([1.0, np.nan, 3.0, 4.0])
    points = scatter_points(x, y)
    # Остаются только пары, где обе переменные заполнены.
    assert len(points) == 2
    assert points[0].x == 1.0
    assert points[1].x == 4.0


# ------------------------------------------------------------- команды


def test_histogram_chart_data():
    dataset = _dataset()
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="histogram", variables=["x"], bins=5)
    )
    assert data.kind == "histogram"
    assert data.n == 10
    assert sum(data.bin_counts) == 10
    assert data.mean_value == pytest.approx(5.5, abs=1e-9)
    assert data.median_value == pytest.approx(5.5, abs=1e-9)


def test_boxplot_chart_data():
    dataset = _dataset()
    data = build_chart_data(ChartCommand(dataset=dataset, kind="boxplot", variables=["x"]))
    assert data.kind == "boxplot"
    assert data.boxes[0]["median"] == pytest.approx(5.5, abs=1e-9)


def test_boxplot_groups_by_category():
    """С выбранной категорией должен быть ящик на каждую группу."""
    dataset = _dataset()
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="boxplot", variables=["x"], category="group")
    )
    assert [box["label"] for box in data.boxes] == ["1", "2", "3"]
    assert [box["n"] for box in data.boxes] == [2, 3, 5]
    # Группа 1: x = 1,2 -> медиана 1,5; группа 2: 3,4,5 -> 4; группа 3: 6..10 -> 8.
    assert data.boxes[0]["median"] == pytest.approx(1.5)
    assert data.boxes[1]["median"] == pytest.approx(4.0)
    assert data.boxes[2]["median"] == pytest.approx(8.0)
    assert "групп: 3" in chart_caption(data)
    assert "BY group" in ChartCommand(
        dataset=dataset, kind="boxplot", variables=["x"], category="group"
    ).syntax()


def test_boxplot_grouping_ignores_missing_category_values():
    dataset = Dataset.from_records(
        {
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "group": ["a", "a", "b", None, "b", "a"],
        }
    )
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="boxplot", variables=["value"], category="group")
    )
    assert [box["label"] for box in data.boxes] == ["a", "b"]
    assert all(box["n"] > 0 for box in data.boxes)


def test_scatter_chart_data_has_perfect_correlation():
    """y = 2x: корреляция должна быть ровно 1."""
    dataset = _dataset()
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="scatter", variables=["x", "y"])
    )
    assert data.correlation == pytest.approx(1.0, abs=1e-9)
    assert data.regression is not None
    slope, intercept = data.regression
    assert slope == pytest.approx(2.0, abs=1e-9)
    assert intercept == pytest.approx(0.0, abs=1e-9)


def test_bar_chart_data_uses_value_labels():
    """Коды категорий должны превратиться в метки, а не остаться числами."""
    dataset = demo_dataset(n=80, seed=3)
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="bar", variables=["income"], category="gender")
    )
    assert data.kind == "bar"
    assert len(data.categories) == len(data.values)
    assert sum(data.values) == data.n
    assert all(not category.isdigit() for category in data.categories)


def test_pie_chart_percents_sum_to_hundred():
    dataset = demo_dataset(n=90, seed=5)
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="pie", variables=["income"], category="city")
    )
    assert sum(data.percents) == pytest.approx(100.0, abs=1e-6)


def test_line_chart_averages_by_category():
    dataset = _dataset()
    data = build_chart_data(
        ChartCommand(dataset=dataset, kind="line", variables=["y"], category="group")
    )
    assert data.kind == "line"
    assert len(data.line_x) == 3
    # Группа 1: значения 2 и 4, среднее 3.
    assert data.line_y[0] == pytest.approx(3.0, abs=1e-9)


def test_chart_command_rejects_two_variables_for_histogram():
    dataset = _dataset()
    with pytest.raises(CommandError):
        ChartCommand(dataset=dataset, kind="histogram", variables=["x", "y"]).execute()


def test_chart_command_rejects_one_variable_for_scatter():
    dataset = _dataset()
    with pytest.raises(CommandError):
        ChartCommand(dataset=dataset, kind="scatter", variables=["x"]).execute()


def test_bar_chart_does_not_require_numeric_variable():
    """Столбцам нужна только категория: переменная в форме была лишней."""
    dataset = demo_dataset(n=40, seed=2)
    data = build_chart_data(ChartCommand(dataset=dataset, kind="bar", category="gender"))
    assert sum(data.values) == data.n
    assert data.categories


def test_pie_chart_does_not_require_numeric_variable():
    dataset = demo_dataset(n=40, seed=2)
    data = build_chart_data(ChartCommand(dataset=dataset, kind="pie", category="city"))
    assert sum(data.percents) == pytest.approx(100.0, abs=1e-6)


def test_chart_command_requires_category_for_bar():
    dataset = _dataset()
    with pytest.raises(CommandError):
        ChartCommand(dataset=dataset, kind="bar", variables=["x"]).execute()


def test_chart_command_result_has_numbers_table():
    """В выводе должна быть таблица с числами, а не только подпись."""
    dataset = _dataset()
    result = ChartCommand(dataset=dataset, kind="histogram", variables=["x"]).execute()
    assert result.tables
    table = result.tables[0]
    assert "Частота" in [column.label for column in table.columns]
    assert result.syntax.startswith("GRAPH")


def test_chart_caption_mentions_sample_size():
    dataset = _dataset()
    data = build_chart_data(ChartCommand(dataset=dataset, kind="histogram", variables=["x"]))
    caption = chart_caption(data)
    assert "N = 10" in caption


def test_chart_warns_when_no_data():
    dataset = Dataset.from_records({"x": [np.nan, np.nan]})
    result = ChartCommand(dataset=dataset, kind="histogram", variables=["x"]).execute()
    assert result.warnings

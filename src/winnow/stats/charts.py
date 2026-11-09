"""Данные для графиков.

Здесь считается всё, что можно проверить тестами: интервалы гистограммы, квартили
ящика с усами, агрегаты столбчатой диаграммы, точки рассеяния. Само рисование
живёт в интерфейсе (`ui/chart_window.py`) и получает уже готовые числа.

Разделение не формальное: расчёт интервалов и квартилей - это то, где легко
ошибиться на единицу или на пол-интервала, и такие ошибки видно только на
проверяемых числах. Квартили считаются тем же методом, что и в описательных
статистиках, чтобы график и таблица не расходились.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from winnow.stats.command import Command, CommandError
from winnow.stats.result import Column, Result, Table

CHART_TYPES: list[tuple[str, str]] = [
    ("Гистограмма", "histogram"),
    ("Ящик с усами", "boxplot"),
    ("Диаграмма рассеяния", "scatter"),
    ("Столбчатая диаграмма", "bar"),
    ("Круговая диаграмма", "pie"),
    ("Линия средних", "line"),
]

CHART_TITLES = {key: title for title, key in CHART_TYPES}
CHART_KEYS = frozenset(CHART_TITLES)


@dataclass
class ChartCommand(Command):
    """Команда построения графика."""

    PROCEDURE: ClassVar[str] = "GRAPH"
    TITLE: ClassVar[str] = "График"
    KEY: ClassVar[str] = "graph"

    kind: str = "histogram"
    variables: list[str] = field(default_factory=list)
    category: str | None = None
    group_by: str | None = None
    bins: int = 0                  # 0 - правило Стёрджесса
    show_normal: bool = False
    show_mean: bool = True
    title: str = ""
    x_label: str = ""
    y_label: str = ""

    def validate(self) -> None:
        if self.dataset is None:
            raise CommandError("Команда не связана с набором данных")
        if self.kind not in CHART_KEYS:
            raise CommandError(f"Неизвестный вид графика: {self.kind!r}")

        # Круговой и столбчатой диаграммам нужна только категория: они показывают
        # частоты, а не значения числовой переменной. Раньше здесь требовалась
        # ещё и переменная, которую движок всё равно не использовал.
        if self.kind in ("bar", "pie"):
            if not self.category:
                raise CommandError("Выберите переменную для категорий")
            if self.category not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {self.category}")
            if self.bins < 0:
                raise CommandError("Число интервалов не может быть отрицательным")
            return

        if not self.variables:
            raise CommandError("Выберите хотя бы одну переменную")
        for name in self.variables:
            if name not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {name}")

        if self.kind in ("histogram", "boxplot") and len(self.variables) > 1:
            # Гистограмма и ящик показывают распределение; несколько переменных
            # на одном графике читались бы плохо, поэтому их строят по одной.
            raise CommandError(
                f"График «{CHART_TITLES[self.kind]}» строится по одной переменной"
            )
        if self.kind in ("histogram", "boxplot") and not self.dataset.var(
            self.variables[0]
        ).is_numeric:
            raise CommandError("Для этого графика нужна числовая переменная")
        if self.kind == "scatter" and len(self.variables) < 2:
            raise CommandError("Для диаграммы рассеяния нужны две переменные: X и Y")
        if self.kind == "line":
            if not self.category:
                raise CommandError("Выберите переменную для категорий")
            if self.category not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {self.category}")
            if not self.dataset.var(self.variables[0]).is_numeric:
                raise CommandError("Для линии средних нужна числовая переменная")
        # Для ящика категория необязательна: без неё один ящик, с ней — по
        # ящику на группу. Это то, чего ждёт человек, выбирая «Категории».
        if self.kind == "boxplot" and self.category:
            if self.category not in self.dataset.variables:
                raise CommandError(f"Переменная не найдена: {self.category}")
        if self.bins < 0:
            raise CommandError("Число интервалов не может быть отрицательным")

    def syntax(self) -> str:
        if self.kind == "histogram":
            return (
                "GRAPH\n"
                f"  /HISTOGRAM={self.variables[0]}\n"
                "  /MISSING=LISTWISE."
            )
        if self.kind == "boxplot":
            return (
                "GRAPH\n"
                f"  /BOXPLOT={self.variables[0]}"
                + (f" BY {self.category}" if self.category else "")
                + "\n  /MISSING=LISTWISE."
            )
        if self.kind == "scatter":
            return (
                "GRAPH\n"
                f"  /SCATTERPLOT={self.variables[0]} WITH {self.variables[1]}\n"
                "  /MISSING=LISTWISE."
            )
        if self.kind == "bar":
            return f"GRAPH\n  /BAR={self.category}\n  /MISSING=LISTWISE."
        if self.kind == "pie":
            return f"GRAPH\n  /PIE={self.category}\n  /MISSING=LISTWISE."
        return (
            "GRAPH\n"
            f"  /LINE(SIMPLE)={self.variables[0]} BY {self.category}\n"
            "  /MISSING=LISTWISE."
        )


# ---------------------------------------------------------------------------
# Описания данных графика
# ---------------------------------------------------------------------------


@dataclass
class ScatterPoint:
    x: float
    y: float
    label: str = ""


@dataclass
class ChartData:
    """Всё, что нужно для рисования графика."""

    kind: str
    title: str
    x_label: str = ""
    y_label: str = ""

    # Гистограмма
    bin_edges: list[float] = field(default_factory=list)
    bin_counts: list[int] = field(default_factory=list)
    normal_curve: tuple[list[float], list[float]] | None = None
    mean_value: float | None = None
    median_value: float | None = None

    # Столбчатая и круговая
    categories: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    percents: list[float] = field(default_factory=list)

    # Ящик с усами
    boxes: list[dict[str, Any]] = field(default_factory=list)
    outliers: list[float] = field(default_factory=list)

    # Рассеяние
    points: list[ScatterPoint] = field(default_factory=list)
    regression: tuple[float, float] | None = None  # наклон и свободный член
    correlation: float | None = None

    # Линия средних
    line_x: list[str] = field(default_factory=list)
    line_y: list[float] = field(default_factory=list)
    line_errors: list[float] = field(default_factory=list)

    n: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Расчёт данных
# ---------------------------------------------------------------------------


def _numeric(dataset, name: str) -> pd.Series:
    """Числовой ряд переменной с учётом пропусков, отбора и разбиения."""
    frame = dataset.analysis_frame([name])
    return pd.to_numeric(frame[name], errors="coerce").dropna()


def _category_series(dataset, name: str) -> pd.Series:
    """Категориальный ряд: метки значений вместо кодов."""
    frame = dataset.analysis_frame([name])
    series = frame[name].dropna()
    variable = dataset.var(name)
    return series.map(lambda value: variable.label_for(value))


def sturges_bins(count: int) -> int:
    """Число интервалов по правилу Стёрджесса.

    Правило даёт число интервалов, растущее как логарифм объёма выборки. Это
    разумное значение по умолчанию: слишком мало интервалов скрывает форму
    распределения, слишком много - превращает график в шум.
    """
    if count < 2:
        return 1
    return max(1, int(math.ceil(math.log2(count) + 1)))


def histogram(values: np.ndarray, bins: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Интервалы и частоты гистограммы.

    Возвращает границы интервалов (на одну больше, чем интервалов) и частоты.
    """
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size == 0:
        return np.array([]), np.array([])
    if bins <= 0:
        bins = sturges_bins(data.size)
    counts, edges = np.histogram(data, bins=bins)
    return edges, counts


def normal_curve(values: np.ndarray, bins: int, points: int = 80) -> tuple[list[float], list[float]]:
    """Нормальная кривая, наложенная на гистограмму.

    Плотность переводится в частоты того же масштаба, что и столбцы: иначе
    кривая и столбцы оказались бы в разных единицах и сравнение было бы ложным.
    """
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size < 3:
        return [], []
    mean = float(np.mean(data))
    std = float(np.std(data, ddof=1))
    if std <= 0:
        return [], []
    low, high = float(np.min(data)), float(np.max(data))
    width = (high - low) / max(bins, 1)
    xs = np.linspace(low, high, points)
    density = np.exp(-0.5 * ((xs - mean) / std) ** 2) / (std * math.sqrt(2 * math.pi))
    return xs.tolist(), (density * data.size * width).tolist()


def box_statistics(values: np.ndarray) -> dict[str, Any]:
    """Статистики ящика с усами: квартили, границы усов, выбросы.

    Усы доходят до крайних значений внутри полутора межквартильных размахов от
    квартилей, всё дальше - выбросы. Это стандартное правило, и оно совпадает с
    тем, что показывает SPSS.
    """
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size == 0:
        return {}
    q1 = float(np.percentile(data, 25))
    median = float(np.percentile(data, 50))
    q3 = float(np.percentile(data, 75))
    iqr = q3 - q1
    low_fence = q1 - 1.5 * iqr
    high_fence = q3 + 1.5 * iqr
    inside = data[(data >= low_fence) & (data <= high_fence)]
    lower_whisker = float(np.min(inside)) if inside.size else q1
    upper_whisker = float(np.max(inside)) if inside.size else q3
    outliers = data[(data < low_fence) | (data > high_fence)]
    return {
        "q1": q1,
        "median": median,
        "q3": q3,
        "iqr": iqr,
        "lower_whisker": lower_whisker,
        "upper_whisker": upper_whisker,
        "minimum": float(np.min(data)),
        "maximum": float(np.max(data)),
        "mean": float(np.mean(data)),
        "n": int(data.size),
        "outliers": outliers.tolist(),
    }


def category_counts(labels: pd.Series) -> tuple[list[str], list[int]]:
    """Частоты категорий с сохранением порядка появления в данных."""
    counts = labels.value_counts(sort=False)
    return [str(value) for value in counts.index.tolist()], [int(value) for value in counts.tolist()]


def scatter_points(x: pd.Series, y: pd.Series) -> list[ScatterPoint]:
    """Точки рассеяния по парам без пропусков."""
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")})
    frame = frame.dropna()
    return [
        ScatterPoint(x=float(row.x), y=float(row.y))
        for row in frame.itertuples(index=False)
    ]


def build_chart_data(command: ChartCommand) -> ChartData:
    """Считает данные графика по команде."""
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    title = command.title or f"{CHART_TITLES[command.kind]}"

    if command.kind == "histogram":
        name = command.variables[0]
        values = _numeric(dataset, name).to_numpy()
        edges, counts = histogram(values, command.bins)
        data = ChartData(
            kind="histogram",
            title=title,
            x_label=command.x_label or dataset.var(name).display_name,
            y_label=command.y_label or "Частота",
            bin_edges=edges.tolist(),
            bin_counts=counts.tolist(),
            n=int(values.size),
        )
        if command.show_normal:
            xs, ys = normal_curve(values, len(counts))
            data.normal_curve = (xs, ys)
        if command.show_mean and values.size:
            data.mean_value = float(np.mean(values))
            data.median_value = float(np.median(values))
        return data

    if command.kind == "boxplot":
        name = command.variables[0]
        if command.category:
            # Ящик по группам: одна категория — один ящик. Без этого поле
            # «Категории» в форме выглядело бы неработающим.
            frame = dataset.analysis_frame([name, command.category]).dropna()
            values = pd.to_numeric(frame[name], errors="coerce")
            labels = frame[command.category].map(
                lambda value: dataset.var(command.category).label_for(value)
            )
            working = pd.DataFrame({"value": values, "group": labels}).dropna()
            boxes: list[dict[str, Any]] = []
            outliers: list[float] = []
            for group, subset in working.groupby("group", sort=False):
                statistics = box_statistics(subset["value"].to_numpy(dtype=float))
                if not statistics:
                    continue
                statistics["label"] = str(group)
                statistics["name"] = str(group)
                boxes.append(statistics)
                outliers.extend(float(value) for value in statistics["outliers"])
            data = ChartData(
                kind="boxplot",
                title=title,
                x_label=command.x_label or dataset.var(command.category).display_name,
                y_label=command.y_label or dataset.var(name).display_name,
                boxes=boxes,
                outliers=outliers,
                n=int(len(working)),
            )
            return data

        values = _numeric(dataset, name).to_numpy()
        statistics = box_statistics(values)
        if not statistics:
            return ChartData(kind="boxplot", title=title, n=0)
        data = ChartData(
            kind="boxplot",
            title=title,
            x_label=command.x_label or dataset.var(name).display_name,
            y_label=command.y_label or dataset.var(name).display_name,
            boxes=[statistics],
            outliers=[float(value) for value in statistics["outliers"]],
            n=int(statistics["n"]),
        )
        return data

    if command.kind == "scatter":
        x_name, y_name = command.variables[0], command.variables[1]
        frame = dataset.analysis_frame([x_name, y_name])
        points = scatter_points(frame[x_name], frame[y_name])
        data = ChartData(
            kind="scatter",
            title=title,
            x_label=command.x_label or dataset.var(x_name).display_name,
            y_label=command.y_label or dataset.var(y_name).display_name,
            points=points,
            n=len(points),
        )
        if len(points) >= 3:
            xs = np.array([point.x for point in points])
            ys = np.array([point.y for point in points])
            if np.std(xs) > 0 and np.std(ys) > 0:
                slope, intercept = np.polyfit(xs, ys, 1)
                data.regression = (float(slope), float(intercept))
                data.correlation = float(np.corrcoef(xs, ys)[0, 1])
                data.notes.append(
                    f"Линия регрессии: y = {intercept:.3f} "
                    f"{'+' if slope >= 0 else '-'} {abs(slope):.3f}·x"
                )
                data.notes.append(f"Корреляция Пирсона: r = {data.correlation:.3f}")
        return data

    if command.kind in ("bar", "pie"):
        labels = _category_series(dataset, command.category)
        categories, counts = category_counts(labels)
        total = sum(counts)
        data = ChartData(
            kind=command.kind,
            title=title,
            x_label=command.x_label or dataset.var(command.category).display_name,
            y_label=command.y_label or "Количество",
            categories=categories,
            values=[float(value) for value in counts],
            percents=[100.0 * value / total if total else 0.0 for value in counts],
            n=total,
        )
        return data

    # Линия средних по категориям.
    name = command.variables[0]
    frame = dataset.analysis_frame([name, command.category])
    numeric = pd.to_numeric(frame[name], errors="coerce")
    working = pd.DataFrame(
        {"value": numeric, "category": frame[command.category].map(
            lambda value: dataset.var(command.category).label_for(value)
        )}
    ).dropna()
    grouped = working.groupby("category", sort=False)["value"]
    categories = [str(value) for value in grouped.groups.keys()]
    means = [float(value) for value in grouped.mean().tolist()]
    errors = [
        float(value / math.sqrt(max(count, 1)))
        for value, count in zip(grouped.std(ddof=1).fillna(0.0).tolist(), grouped.count().tolist())
    ]
    data = ChartData(
        kind="line",
        title=title,
        x_label=command.x_label or dataset.var(command.category).display_name,
        y_label=command.y_label or dataset.var(name).display_name,
        line_x=categories,
        line_y=means,
        line_errors=errors,
        n=int(len(working)),
    )
    return data


def chart_caption(data: ChartData) -> str:
    """Подпись под графиком: что именно показано."""
    if data.kind == "histogram":
        parts = [f"N = {data.n}", f"интервалов: {len(data.bin_counts)}"]
        if data.mean_value is not None:
            parts.append(f"среднее: {data.mean_value:.3f}")
        if data.median_value is not None:
            parts.append(f"медиана: {data.median_value:.3f}")
        return "; ".join(parts)
    if data.kind == "boxplot" and data.boxes:
        total = sum(int(box.get("n", 0)) for box in data.boxes)
        parts = [f"N = {total}"]
        if len(data.boxes) > 1:
            parts.append(f"групп: {len(data.boxes)}")
        parts.append(f"выбросов: {len(data.outliers)}")
        return "; ".join(parts)
    if data.kind == "scatter":
        parts = [f"N = {data.n}"]
        if data.correlation is not None:
            parts.append(f"r = {data.correlation:.3f}")
        return "; ".join(parts)
    if data.kind in ("bar", "pie"):
        return f"Всего наблюдений: {data.n}; категорий: {len(data.categories)}"
    return f"N = {data.n}; категорий: {len(data.line_x)}"


def run(command: ChartCommand) -> Result:
    """График в выводе: таблица с числами и подпись.

    Сам рисунок показывается в отдельном окне, а в дереве вывода остаётся
    таблица с теми числами, по которым график построен. Это важно для отчёта:
    по графику нельзя проверить значения, а по таблице можно.
    """
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    data = build_chart_data(command)
    result = Result(procedure=command.PROCEDURE, title=CHART_TITLES[command.kind], syntax=command.syntax())
    result.add_table(_data_table(data, command))
    result.note(f"{data.title}: {chart_caption(data)}")
    for note in data.notes:
        result.note(note)
    if data.n == 0:
        result.warn("Для графика не осталось данных: проверьте пропуски и отбор кейсов")
    return result


def _data_table(data: ChartData, command: ChartCommand) -> Table:
    """Числовая основа графика - то, что можно проверить и выгрузить."""
    if data.kind == "histogram":
        table = Table(
            title=f"Частоты интервалов: {data.x_label}",
            columns=[
                Column("Интервал", align="left", is_metric=False),
                Column("Частота", decimals=0),
                Column("Доля", decimals=1, suffix="%"),
                Column("Накопленная", decimals=1, suffix="%"),
            ],
        )
        total = sum(data.bin_counts) or 1
        cumulative = 0
        for index, count in enumerate(data.bin_counts):
            share = 100.0 * count / total
            cumulative += share
            low, high = data.bin_edges[index], data.bin_edges[index + 1]
            table.add_row([f"[{low:.3f}; {high:.3f})", count, share, cumulative])
        table.footnote(
            f"Интервалы: {len(data.bin_counts)}. Левая граница входит в интервал, "
            "правая - нет."
        )
        return table

    if data.kind == "boxplot":
        if len(data.boxes) > 1 or any(box.get("label") for box in data.boxes):
            table = Table(
                title=f"Статистики ящика с усами: {data.x_label}",
                columns=[
                    Column("Группа", align="left", is_metric=False),
                    Column("N", decimals=0),
                    Column("Q1", decimals=3),
                    Column("Медиана", decimals=3),
                    Column("Q3", decimals=3),
                    Column("Минимум", decimals=3),
                    Column("Максимум", decimals=3),
                    Column("Выбросов", decimals=0),
                ],
                footnotes=[
                    "Усы доходят до крайних значений внутри 1.5 межквартильных "
                    "размаха от квартилей; всё дальше считается выбросами."
                ],
            )
            for box in data.boxes:
                table.add_row(
                    [
                        box.get("label") or box.get("name") or "Все наблюдения",
                        float(box["n"]),
                        box["q1"],
                        box["median"],
                        box["q3"],
                        box["minimum"],
                        box["maximum"],
                        float(len(box.get("outliers", []))),
                    ]
                )
            return table

        table = Table(
            title=f"Статистики ящика с усами: {data.x_label}",
            columns=[
                Column("Показатель", align="left", is_metric=False),
                Column("Значение", decimals=3),
            ],
            footnotes=[
                "Усы доходят до крайних значений внутри 1.5 межквартильных размаха "
                "от квартилей; всё дальше считается выбросами."
            ],
        )
        if data.boxes:
            box = data.boxes[0]
            table.add_row(["N", float(box["n"])])
            table.add_row(["Минимум", box["minimum"]])
            table.add_row(["Нижний квартиль (Q1)", box["q1"]])
            table.add_row(["Медиана", box["median"]])
            table.add_row(["Верхний квартиль (Q3)", box["q3"]])
            table.add_row(["Максимум", box["maximum"]])
            table.add_row(["Межквартильный размах", box["iqr"]])
            table.add_row(["Нижний ус", box["lower_whisker"]])
            table.add_row(["Верхний ус", box["upper_whisker"]])
            table.add_row(["Среднее", box["mean"]])
            table.add_row(["Выбросов", float(len(data.outliers))])
        return table

    if data.kind in ("bar", "pie"):
        table = Table(
            title=f"Частоты категорий: {data.x_label}",
            columns=[
                Column(data.x_label or "Категория", align="left", is_metric=False),
                Column("Частота", decimals=0),
                Column("Доля", decimals=1, suffix="%"),
            ],
        )
        for category, value, percent in zip(data.categories, data.values, data.percents):
            table.add_row([category, value, percent])
        table.add_row(["Всего", sum(data.values), 100.0 if data.values else None])
        return table

    if data.kind == "scatter":
        table = Table(
            title=f"Связь: {data.x_label} и {data.y_label}",
            columns=[
                Column("Показатель", align="left", is_metric=False),
                Column("Значение", decimals=3),
            ],
            footnotes=["Точки графика - наблюдения без пропусков по обеим переменным."],
        )
        table.add_row(["Число точек", float(data.n)])
        if data.correlation is not None:
            table.add_row(["Корреляция Пирсона", data.correlation])
        if data.regression is not None:
            slope, intercept = data.regression
            table.add_row(["Наклон линии", slope])
            table.add_row(["Свободный член", intercept])
        return table

    # Линия средних.
    table = Table(
        title=f"Средние по категориям: {data.y_label}",
        columns=[
            Column(data.x_label or "Категория", align="left", is_metric=False),
            Column("Среднее", decimals=3),
            Column("Стд. ошибка", decimals=3),
        ],
    )
    for category, mean, error in zip(data.line_x, data.line_y, data.line_errors):
        table.add_row([category, mean, error])
    table.footnote("Отрезки на графике - стандартная ошибка среднего.")
    return table


__all__ = [
    "CHART_KEYS",
    "CHART_TITLES",
    "CHART_TYPES",
    "ChartCommand",
    "ChartData",
    "ScatterPoint",
    "box_statistics",
    "build_chart_data",
    "category_counts",
    "chart_caption",
    "histogram",
    "normal_curve",
    "run",
    "scatter_points",
    "sturges_bins",
]

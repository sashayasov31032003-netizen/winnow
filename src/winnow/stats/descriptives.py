"""Описательные статистики.

Одна строка на переменную - так же, как в SPSS. Каждая статистика снабжена
понятной подписью, потому что половина обращений в поддержку любого
статистического пакета - это вопросы "что здесь написано".
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import CommandError, DescriptivesCommand
from winnow.stats.common import category_label, ordered_categories, t_ci, valid_values
from winnow.stats.profile import profile_variable
from winnow.stats.result import Column, Result, Table

# Подписи статистик: ключ -> подпись в таблице.
STATISTIC_LABELS: dict[str, str] = {
    "n": "N",
    "missing": "Пропущено",
    "mean": "Среднее",
    "median": "Медиана",
    "std": "Стд. отклонение",
    "variance": "Дисперсия",
    "min": "Минимум",
    "max": "Максимум",
    "range": "Размах",
    "skewness": "Асимметрия",
    "kurtosis": "Эксцесс",
    "sem": "Стд. ошибка среднего",
    "sum": "Сумма",
    "mode": "Мода",
    "iqr": "Межквартильный размах",
}


def _describes_categories(dataset, name: str) -> bool:
    """Описывать ли переменную распределением ответов, а не средним.

    Да - если она объявлена категориальной или порядковой, либо если она
    очевидно не измерение: два значения, одно значение или отметка «выбрано».
    """
    variable = dataset.var(name)
    if variable.measure.is_categorical:
        return True
    profile = profile_variable(dataset, name)
    return bool(profile.is_binary or profile.is_constant or profile.looks_like_checkbox)


def _distribution_table(
    name: str, pairs: list[tuple[str, int]], n_valid: int
) -> Table:
    """Распределение ответов категориальной переменной.

    Показывается рядом со средними: у категориальной переменной среднее по кодам
    смысла не имеет, а распределение - это и есть её описание.
    """
    table = Table(
        title=f"Распределение ответов: {name}",
        columns=[
            Column("Ответ", align="left", is_metric=False),
            Column("Частота", decimals=0),
            Column("Процент", decimals=1, suffix="%"),
        ],
    )
    for label, count in pairs:
        percent = count / n_valid * 100 if n_valid else None
        table.add_row([label, count, percent])
    table.add_row(["Всего ответивших", n_valid, 100.0 if n_valid else None])
    table.footnote(
        "Значения этой переменной - коды ответов, поэтому среднее по ним не "
        "рассчитывается."
    )
    return table


def _as_float(value: object) -> float | None:
    """Приводит значение статистики к числу, если оно вообще посчитано."""
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _variable_stats(values: np.ndarray, total: int, requested: list[str]) -> dict[str, object]:
    """Считает запрошенные статистики для одного числового ряда."""
    n = int(values.size)
    out: dict[str, object] = {"n": n, "missing": total - n}
    if n == 0:
        return out

    std = float(np.std(values, ddof=1)) if n > 1 else float("nan")
    mean = float(np.mean(values))

    if "mean" in requested:
        out["mean"] = mean
    if "median" in requested:
        out["median"] = float(np.median(values))
    if "std" in requested:
        out["std"] = std
    if "variance" in requested:
        out["variance"] = float(np.var(values, ddof=1)) if n > 1 else float("nan")
    if "min" in requested:
        out["min"] = float(np.min(values))
    if "max" in requested:
        out["max"] = float(np.max(values))
    if "range" in requested:
        out["range"] = float(np.max(values) - np.min(values))
    if "sem" in requested:
        out["sem"] = std / math.sqrt(n) if n > 1 else float("nan")
    if "sum" in requested:
        out["sum"] = float(np.sum(values))
    if "skewness" in requested:
        out["skewness"] = float(sps.skew(values, bias=False)) if n > 2 else float("nan")
    if "kurtosis" in requested:
        out["kurtosis"] = float(sps.kurtosis(values, bias=False)) if n > 3 else float("nan")
    if "mode" in requested:
        modes = pd.Series(values).mode()
        out["mode"] = float(modes.iloc[0]) if len(modes) else float("nan")
    if "iqr" in requested and n > 1:
        q1, q3 = np.percentile(values, [25, 75])
        out["iqr"] = float(q3 - q1)
    return out


def _strata(dataset, split_by: str | None) -> list[tuple[str, pd.Series | None]]:
    """Готовит разбиение на страты: список (подпись, маска строк аналитического среза)."""
    if not split_by:
        return [("", None)]

    variable = dataset.var(split_by)
    series = dataset.analysis_frame([split_by])[split_by]
    groups: list[tuple[str, pd.Series]] = []
    for value in ordered_categories(series, variable.value_labels):
        mask = series == value
        if not mask.any():
            continue
        label = variable.label or variable.name
        groups.append((f"{label} = {category_label(value, variable.value_labels)}", mask))
    return groups or [("", None)]


def run(command: DescriptivesCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    requested = list(command.statistics)
    confidence = command.confidence
    frame = dataset.analysis_frame()  # один срез на все расчёты
    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())

    if dataset.weight_values() is not None:
        result.note(f"Учтены веса кейсов: {dataset.weight_var}")

    numeric_names = [name for name in command.variables if dataset.var(name).is_numeric]
    for name in command.variables:
        if not dataset.var(name).is_numeric:
            result.warn(f"Переменная {name!r} пропущена: описательные статистики требуют чисел")
    if not numeric_names:
        result.warn("Ни одной числовой переменной не выбрано")
        return result

    total_cases = int(len(frame))

    # Переменные делятся на количественные и «с готовыми вариантами ответа».
    # Решает не только объявленный уровень измерения: в чужих выгрузках
    # количественной часто помечена переменная с двумя значениями - например,
    # возраст, перекодированный в «младшее/среднее поколение». Среднее «0,40» по
    # такой переменной выглядит как факт, хотя это код поколения.
    #
    # Но и обратная ошибка дорога: на малой выборке у настоящего показателя тоже
    # бывает мало различных значений. Поэтому «не показатель» объявляется только
    # в однозначных случаях - переменная с двумя значениями, константа или
    # отметка «выбрано», - а не просто по числу уникальных значений.
    categorical_names = [
        name for name in numeric_names if _describes_categories(dataset, name)
    ]
    code_names = [
        dataset.var(name).label or name
        for name in categorical_names
        if dataset.var(name).measure.is_nominal
    ]

    for stratum_label, mask in _strata(dataset, command.split_by):
        rows: list[list[object]] = []
        ci_rows: list[list[object]] = []
        described: list[tuple[str, float, float, float | None, float | None, int]] = []
        distributions: list[tuple[str, list[tuple[str, int]], int]] = []
        distribution_tables: list[tuple[str, list[tuple[str, int]], int]] = []
        missing_info: list[tuple[str, int]] = []

        for name in numeric_names:
            variable = dataset.var(name)
            series = pd.to_numeric(frame[name], errors="coerce")
            if mask is not None:
                series = series[mask.to_numpy()]

            values = valid_values(series)
            stats = _variable_stats(values, int(len(series)), requested)
            rows.append([variable.display_name] + [stats.get(key) for key in requested])

            # Числа для вывода «простыми словами» собираются здесь же: второй раз
            # их считать незачем.
            mean = stats.get("mean")
            if mean is not None and name not in categorical_names:
                described.append(
                    (
                        variable.label or name,
                        float(mean),
                        float(stats.get("std") or 0.0),
                        _as_float(stats.get("min")),
                        _as_float(stats.get("max")),
                        int(stats.get("n") or 0),
                    )
                )
            count_missing = int(stats.get("missing") or 0)
            if count_missing:
                missing_info.append((variable.label or name, count_missing))

            if confidence and values.size > 1:
                mean = float(np.mean(values))
                std = float(np.std(values, ddof=1))
                low, high = t_ci(mean, std, values.size, confidence)
                ci_rows.append([variable.display_name, mean, low, high, std])

        for name in categorical_names:
            variable = dataset.var(name)
            series = dataset.categorical_series(name)
            if mask is not None:
                series = series[mask.to_numpy()]
            valid_series = series.dropna()
            n_valid = int(len(valid_series))
            if n_valid == 0:
                continue
            counts = valid_series.value_counts()
            pairs = [
                (category_label(value, variable.value_labels), int(counts.get(value, 0)))
                for value in ordered_categories(valid_series, variable.value_labels)
            ]
            distributions.append((variable.label or name, pairs, n_valid))
            distribution_tables.append((variable.display_name, pairs, n_valid))

        columns = [Column("Переменная", align="left", is_metric=False)]
        columns += [Column(STATISTIC_LABELS.get(key, key), decimals=2) for key in requested]

        title = "Описательные статистики"
        if stratum_label:
            title += f" ({stratum_label})"
        table = Table(title=title, columns=columns, rows=rows)
        table.footnote("Стд. отклонение и дисперсия рассчитаны со знаменателем (N - 1).")
        for name in numeric_names:
            spec = dataset.var(name).missing
            if not spec.is_empty:
                table.footnote(f"Пропущенные значения ({name}): {spec.summary()}")
        result.add_table(table)

        # Распределения категориальных переменных идут после средних: сначала
        # «сколько в среднем», потом «как распределились ответы». Обратный
        # порядок читался бы как продолжение таблицы средних, хотя это другая
        # таблица про другое.
        for title, pairs, n_valid in distribution_tables:
            result.add_table(_distribution_table(title, pairs, n_valid))

        # Вывод «простыми словами»: без него «Описать выборку» показывала голую
        # таблицу, и что из неё следует, приходилось догадываться.
        result.add_findings(
            interpretation.describe_sample(
                n_cases=total_cases,
                scales=described,
                categories=distributions,
                code_variables=code_names,
                missing=missing_info,
            )
        )

        if ci_rows:
            ci_table = Table(
                title="Доверительные интервалы для среднего"
                + (f" ({stratum_label})" if stratum_label else ""),
                columns=[
                    Column("Переменная", align="left", is_metric=False),
                    Column("Среднее", decimals=2),
                    Column("Нижняя граница", decimals=2),
                    Column("Верхняя граница", decimals=2),
                    Column("Стд. отклонение", decimals=2),
                ],
                rows=ci_rows,
            )
            ci_table.footnote(f"Доверительный уровень: {confidence * 100:.1f}%")
            result.add_table(ci_table)

    if command.percentiles:
        table = Table(
            title="Процентили",
            columns=[Column("Переменная", align="left", is_metric=False)]
            + [Column(f"{p:g}", decimals=2) for p in command.percentiles],
        )
        for name in numeric_names:
            values = valid_values(frame[name])
            if values.size == 0:
                continue
            table.add_row(
                [dataset.var(name).display_name]
                + [float(np.percentile(values, p)) for p in command.percentiles]
            )
        if table.rows:
            table.footnote("Процентили вычислены методом линейной интерполяции (как в SPSS).")
            result.add_table(table)

    return result


__all__ = ["STATISTIC_LABELS", "run"]

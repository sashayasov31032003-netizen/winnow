"""Анализ надёжности шкалы: альфа Кронбаха и сопутствующие показатели.

Зачем: прежде чем складывать пункты опросника в одну шкалу, нужно показать, что
они действительно измеряют одно и то же. Альфа Кронбаха - самый ожидаемый
показатель, но одного числа мало: нужны ещё «альфа при удалении пункта» (какой
пункт портит шкалу) и корреляция пункта с суммой остальных.

Формулы стандартные, числа проверяются в тестах на данных с известной структурой.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from winnow.stats import interpretation
from winnow.stats.command import CommandError, ReliabilityCommand
from winnow.stats.result import Column, Result, Table


def cronbach_alpha(data: np.ndarray) -> float:
    """Альфа Кронбаха по дисперсиям пунктов.

    Формула: alpha = k / (k - 1) * (1 - сумма дисперсий пунктов / дисперсия суммы).
    """
    n, k = data.shape
    if k < 2 or n < 2:
        return float("nan")
    item_variances = np.var(data, axis=0, ddof=1)
    total = np.sum(data, axis=1)
    total_variance = float(np.var(total, ddof=1))
    if total_variance <= 0:
        return float("nan")
    return float((k / (k - 1)) * (1.0 - float(np.sum(item_variances)) / total_variance))


def mcdonald_omega(data: np.ndarray) -> float:
    """Омега Макдональда - менее смещённая оценка, чем альфа.

    Оценка основана на однфакторной модели: сумма квадратов нагрузок делится на
    общую дисперсию. В отличие от альфы, омега не требует равенства нагрузок.
    """
    n, k = data.shape
    if k < 3 or n < k + 2:
        return float("nan")
    correlation = np.corrcoef(data, rowvar=False)
    if not np.all(np.isfinite(correlation)):
        return float("nan")

    # Однофакторное решение методом главных факторов: берём первую компоненту.
    eigenvalues, eigenvectors = np.linalg.eigh(correlation)
    first = eigenvectors[:, -1]
    loadings = first * math.sqrt(max(eigenvalues[-1], 0.0))
    if float(np.sum(loadings)) < 0:
        loadings = -loadings

    explained = float(np.sum(loadings**2))
    uniqueness = max(k - explained, 1e-12)
    return float(explained / (explained + uniqueness))


def split_half_reliability(data: np.ndarray) -> tuple[float, float]:
    """Надёжность половин: корреляция половин и поправка Спирмена-Брауна.

    Пункты делятся на чётные и нечётные - так половинки сопоставимы по составу.
    """
    n, k = data.shape
    if k < 4 or n < 3:
        return float("nan"), float("nan")
    odd = data[:, 0::2].sum(axis=1)
    even = data[:, 1::2].sum(axis=1)
    if np.std(odd, ddof=1) == 0 or np.std(even, ddof=1) == 0:
        return float("nan"), float("nan")
    correlation = float(np.corrcoef(odd, even)[0, 1])
    if not math.isfinite(correlation) or correlation <= -1.0:
        return correlation, float("nan")
    return correlation, float(2.0 * correlation / (1.0 + correlation))


def corrected_item_total(data: np.ndarray) -> np.ndarray:
    """Корреляция каждого пункта с суммой остальных пунктов."""
    n, k = data.shape
    result = np.full(k, np.nan)
    for index in range(k):
        others = np.delete(data, index, axis=1).sum(axis=1)
        if np.std(data[:, index], ddof=1) == 0 or np.std(others, ddof=1) == 0:
            continue
        result[index] = float(np.corrcoef(data[:, index], others)[0, 1])
    return result


def alpha_if_deleted(data: np.ndarray) -> np.ndarray:
    """Значение альфы, если удалить пункт."""
    n, k = data.shape
    result = np.full(k, np.nan)
    for index in range(k):
        reduced = np.delete(data, index, axis=1)
        result[index] = cronbach_alpha(reduced)
    return result


def _interpret_alpha(value: float) -> str:
    if not math.isfinite(value):
        return "."
    if value >= 0.9:
        return "отличная"
    if value >= 0.8:
        return "хорошая"
    if value >= 0.7:
        return "приемлемая"
    if value >= 0.6:
        return "спорная"
    return "низкая"


def _prepare(dataset, items: list[str]) -> tuple[pd.DataFrame, int, int]:
    """Готовит полные наблюдения: надёжность считается только по полным случаям."""
    frame = dataset.analysis_frame(items)
    total = int(len(frame))
    numeric = pd.DataFrame(
        {name: pd.to_numeric(frame[name], errors="coerce") for name in items}
    )
    complete = numeric.dropna()
    return complete, total, total - int(len(complete))


def run_reliability(command: ReliabilityCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    complete, total, excluded = _prepare(dataset, command.items)

    summary = Table(
        title="Сводка по обработке наблюдений",
        columns=[
            Column("", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Процент", decimals=1, suffix="%"),
        ],
        footnotes=["Надёжность считается только по наблюдениям без пропусков."],
    )
    summary.add_row(["Валидные", len(complete), (100.0 * len(complete) / total) if total else None])
    summary.add_row(["Исключённые", excluded, (100.0 * excluded / total) if total else None])
    summary.add_row(["Всего", total, 100.0 if total else None])
    result.add_table(summary)

    if len(complete) < 3 or len(command.items) < 2:
        result.warn("Слишком мало данных для анализа надёжности")
        return result

    data = complete.to_numpy(dtype=float)
    alpha = cronbach_alpha(data)
    omega = mcdonald_omega(data)
    half_correlation, spearman_brown = split_half_reliability(data)

    statistics = Table(
        title="Надёжность шкалы",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
            Column("Интерпретация", align="left", is_metric=False),
        ],
    )
    statistics.add_row(["Число пунктов", float(len(command.items)), ""])
    statistics.add_row(["Альфа Кронбаха", alpha, _interpret_alpha(alpha)])
    statistics.add_row(["Омега Макдональда", omega, _interpret_alpha(omega)])
    statistics.add_row(["Корреляция половин", half_correlation, ""])
    statistics.add_row(["Надёжность половин (Спирмен-Браун)", spearman_brown, _interpret_alpha(spearman_brown)])
    statistics.footnote(
        "Ориентиры: 0.7 - приемлемо, 0.8 - хорошо, 0.9 - отлично. "
        "Значение ниже 0.6 говорит о том, что пункты измеряют разные вещи."
    )
    statistics.footnote(
        "Омега Макдональда устойчивее альфы: она не предполагает равного вклада пунктов."
    )
    result.add_table(statistics)

    if command.scale_statistics:
        scale = Table(
            title="Статистики шкалы",
            columns=[
                Column("Показатель", align="left", is_metric=False),
                Column("Значение", decimals=3),
            ],
        )
        scale.add_row(["Среднее шкалы", float(np.mean(data.sum(axis=1)))])
        scale.add_row(["Дисперсия шкалы", float(np.var(data.sum(axis=1), ddof=1))])
        scale.add_row(["Стд. отклонение шкалы", float(np.std(data.sum(axis=1), ddof=1))])
        scale.add_row(["Среднее межпунктовых ковариаций", _mean_inter_covariance(data)])
        scale.add_row(["Среднее межпунктовых корреляций", _mean_inter_correlation(data)])
        scale.footnote("Шкала - это сумма (или среднее) всех пунктов.")
        result.add_table(scale)

    if command.item_statistics:
        corrected = corrected_item_total(data)
        deleted = alpha_if_deleted(data)
        table = Table(
            title="Статистики пунктов",
            columns=[
                Column("Пункт", align="left", is_metric=False),
                Column("Среднее", decimals=3),
                Column("Стд. отклонение", decimals=3),
                Column("N", decimals=0),
                Column("Корреляция с суммой остальных", decimals=3),
                Column("Альфа при удалении", decimals=3),
            ],
            footnotes=[
                "Корреляция с суммой остальных ниже 0.3 означает, что пункт "
                "плохо согласуется со шкалой.",
                "Если «альфа при удалении» заметно выше общей альфы, этот пункт "
                "портит шкалу и его стоит исключить.",
            ],
        )
        for index, name in enumerate(command.items):
            table.add_row(
                [
                    dataset.var(name).display_name,
                    float(np.mean(data[:, index])),
                    float(np.std(data[:, index], ddof=1)),
                    len(data),
                    float(corrected[index]) if math.isfinite(corrected[index]) else None,
                    float(deleted[index]) if math.isfinite(deleted[index]) else None,
                ]
            )
        result.add_table(table)

        # Предупреждения о проблемных пунктах: это то, ради чего вообще смотрят
        # на статистики пунктов.
        for index, name in enumerate(command.items):
            if math.isfinite(corrected[index]) and corrected[index] < 0.3:
                result.warn(
                    f"пункт «{dataset.var(name).display_name}» слабо согласуется со шкалой "
                    f"(корреляция с суммой остальных {corrected[index]:.2f})"
                )
            if (
                math.isfinite(deleted[index])
                and math.isfinite(alpha)
                and deleted[index] > alpha + 0.05
            ):
                result.warn(
                    f"без пункта «{dataset.var(name).display_name}» надёжность выросла бы "
                    f"с {alpha:.3f} до {deleted[index]:.3f}"
                )

    if command.inter_item:
        correlation = np.corrcoef(data, rowvar=False)
        names = [dataset.var(name).display_name for name in command.items]
        table = Table(
            title="Межпунктовые корреляции",
            columns=[Column("", align="left", is_metric=False)]
            + [Column(str(index + 1), decimals=3) for index in range(len(names))],
            footnotes=["Номера столбцов соответствуют порядку пунктов в списке."],
        )
        for index, name in enumerate(names):
            table.add_row([f"{index + 1}. {name}"] + [float(value) for value in correlation[index]])
        result.add_table(table)

    result.note(
        f"Надёжность шкалы: альфа Кронбаха = {alpha:.3f} "
        f"({_interpret_alpha(alpha)}), пунктов {len(command.items)}"
    )

    # Вывод «простыми словами»: что из этой альфы следует и можно ли объединять
    # пункты в одну шкалу. Самый «вредный» пункт ищется по альфе при удалении -
    # если статистики пунктов считались.
    worst_item: str | None = None
    worst_alpha: float | None = None
    if command.item_statistics:
        deleted = alpha_if_deleted(data)
        for index, name in enumerate(command.items):
            value = float(deleted[index])
            if not math.isfinite(value):
                continue
            if worst_alpha is None or value > worst_alpha:
                worst_alpha, worst_item = value, dataset.var(name).display_name
    result.add_findings(
        interpretation.reliability(
            items=len(command.items),
            alpha=float(alpha),
            n=len(data),
            worst_item=worst_item,
            worst_alpha=worst_alpha,
        )
    )
    return result


def _mean_inter_covariance(data: np.ndarray) -> float:
    covariance = np.cov(data, rowvar=False)
    k = covariance.shape[0]
    if k < 2:
        return float("nan")
    mask = ~np.eye(k, dtype=bool)
    return float(np.mean(covariance[mask]))


def _mean_inter_correlation(data: np.ndarray) -> float:
    correlation = np.corrcoef(data, rowvar=False)
    k = correlation.shape[0]
    if k < 2:
        return float("nan")
    mask = ~np.eye(k, dtype=bool)
    return float(np.mean(correlation[mask]))


def run(command: ReliabilityCommand) -> Result:
    """Точка входа процедуры для движка."""
    return run_reliability(command)


__all__ = [
    "alpha_if_deleted",
    "corrected_item_total",
    "cronbach_alpha",
    "mcdonald_omega",
    "run",
    "run_reliability",
    "split_half_reliability",
]

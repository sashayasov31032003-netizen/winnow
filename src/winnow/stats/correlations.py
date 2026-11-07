"""Корреляционный анализ: Пирсон, Спирмен, Кендалл.

Матрица выводится целиком (а не только нижний треугольник), потому что
пользователи копируют её в отчёты и ожидают симметричный вид. Пропуски
обрабатываются попарно - это соответствует "Exclude cases pairwise" в SPSS и
сохраняет максимум данных.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.formatting import stars
from winnow.stats import interpretation
from winnow.stats.command import CommandError, CorrelationsCommand
from winnow.stats.result import Column, Result, Table

METHOD_LABELS = {
    "pearson": "Пирсона (r)",
    "spearman": "Спирмена (rho)",
    "kendall": "Кендалла (tau-b)",
}


def _weighted_pearson(
    a: np.ndarray, b: np.ndarray, w: np.ndarray
) -> tuple[int, float, float]:
    """Взвешенный коэффициент Пирсона - тот же, что считает SPSS при WEIGHT BY.

    Средние и ковариация считаются с весами, знаменатель - (сумма весов - 1),
    а значимость - по t с числом степеней свободы (сумма весов - 2). Проверено
    на эталоне: r = 0,954 при N = 22.
    """
    total = float(w.sum())
    if total <= 2:
        return int(total), float("nan"), float("nan")
    mean_a = float((w * a).sum() / total)
    mean_b = float((w * b).sum() / total)
    da, db = a - mean_a, b - mean_b
    covariance = float((w * da * db).sum() / (total - 1))
    var_a = float((w * da * da).sum() / (total - 1))
    var_b = float((w * db * db).sum() / (total - 1))
    if var_a <= 0 or var_b <= 0:
        return int(total), float("nan"), float("nan")
    r = covariance / np.sqrt(var_a * var_b)
    r = float(max(-1.0, min(1.0, r)))
    if abs(r) >= 1.0:
        return int(total), r, 0.0
    t_value = r * np.sqrt((total - 2) / (1 - r * r))
    p = float(2 * sps.t.sf(abs(t_value), total - 2))
    return int(total), r, p


def _pairwise(
    first: np.ndarray,
    second: np.ndarray,
    method: str,
    weights: np.ndarray | None = None,
) -> tuple[int, float, float]:
    mask = np.isfinite(first) & np.isfinite(second)
    if weights is not None:
        mask = mask & np.isfinite(weights)
    a, b = first[mask], second[mask]
    n = int(a.size)
    if n < 3:
        return n, float("nan"), float("nan")

    if weights is not None and method == "pearson":
        return _weighted_pearson(a, b, weights[mask])

    if np.std(a, ddof=1) == 0 or np.std(b, ddof=1) == 0:
        return n, float("nan"), float("nan")

    if method == "pearson":
        r, p = sps.pearsonr(a, b)
    elif method == "spearman":
        r, p = sps.spearmanr(a, b)
    else:
        r, p = sps.kendalltau(a, b, variant="b")
    return n, float(r), float(p)


def run(command: CorrelationsCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    names = command.variables
    frame = dataset.analysis_frame(names)
    columns_data = {
        name: pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float) for name in names
    }

    # Веса берутся по тем же строкам, что и данные: если выравнивание не
    # сошлось, лучше посчитать без весов, чем перепутать строки.
    weights = None
    if dataset.weight_values() is not None:
        try:
            series = pd.to_numeric(
                dataset.analysis_series(dataset.weight_var), errors="coerce"
            )
            candidate = series.to_numpy(dtype=float)
            if candidate.size == len(frame):
                weights = candidate
        except (KeyError, ValueError, TypeError):
            weights = None

    matrix: dict[tuple[int, int], tuple[int, float, float]] = {}

    # Постоянная переменная: все значения одинаковы, и коэффициент корреляции с
    # ней не определяется - делить на её стандартное отклонение нельзя. Раньше
    # программа молча показывала таблицу с точками, без предупреждения и без
    # объяснения, и человек не понимал, что не так.
    constants = [
        name
        for name in names
        if not frame[name].isna().all() and frame[name].nunique(dropna=True) <= 1
    ]
    for name in constants:
        result.warn(
            f"{dataset.var(name).display_name}: переменная не меняется ни у одного "
            "случая, поэтому связь с ней посчитать нельзя"
        )
    if constants:
        result.caution(
            "Связь с постоянной переменной не считается: если все значения "
            "одинаковы, коэффициент не из чего построить. Обычно это отметка в "
            "анкете, которую не выбрал никто."
        )

    for i, first_name in enumerate(names):
        for j, second_name in enumerate(names):
            if j < i:
                continue
            values = _pairwise(columns_data[first_name], columns_data[second_name], command.method)
            matrix[(i, j)] = values
            matrix[(j, i)] = values

    table = Table(
        title=f"Корреляции ({METHOD_LABELS[command.method]})",
        columns=[Column("", align="left", is_metric=False)]
        + [Column(f"{i + 1}", decimals=3) for i in range(len(names))]
        + [Column("N", decimals=0)],
    )

    for i, name in enumerate(names):
        row: list[Any] = [f"{i + 1}. {dataset.var(name).display_name}"]
        for j in range(len(names)):
            n, r, p = matrix[(i, j)]
            if i == j:
                row.append(1.0)
                continue
            if not math.isfinite(r):
                row.append(None)
                continue
            text = f"{r:.3f}"
            if command.flag_significant:
                marks = stars(p)
                if marks:
                    text += marks
            row.append(text)
        # N зависит от пары (попарное исключение пропусков), поэтому в строке
        # показывается минимальное число наблюдений - точные значения ниже.
        sizes = [matrix[(i, j)][0] for j in range(len(names)) if j != i]
        row.append(min(sizes) if sizes else matrix[(i, i)][0])
        table.add_row(row)

    table.footnote("Над диагональю и под диагональю - симметричные значения.")
    if command.flag_significant:
        table.footnote("Значимость: * p < 0.05, ** p < 0.01, *** p < 0.001 (двусторонняя).")
    table.footnote(
        "Пропуски исключены попарно, поэтому N зависит от пары переменных. "
        "В колонке N указано минимальное число наблюдений в строке; "
        "точные значения по парам - в таблице значимости."
    )
    result.add_table(table)

    p_table = Table(
        title="Значимость (двусторонняя, p)",
        columns=[Column("Пара переменных", align="left", is_metric=False)]
        + [Column("N", decimals=0), Column("Коэффициент", decimals=3), Column("p", decimals=3)],
    )
    for i, first_name in enumerate(names):
        for j, second_name in enumerate(names):
            if j <= i:
                continue
            n, r, p = matrix[(i, j)]
            p_table.add_row(
                [
                    f"{dataset.var(first_name).display_name} - "
                    f"{dataset.var(second_name).display_name}",
                    n,
                    r,
                    p,
                ]
            )
    if not command.two_tailed:
        p_table.footnote(
            "ВНИМАНИЕ: запрошена односторонняя значимость; в таблице указаны двусторонние значения."
        )
    p_table.footnote("Размеры выборок указаны попарно (после исключения пропусков).")
    result.add_table(p_table)

    # Вывод «простыми словами» по самой сильной связи: в таблице может быть
    # десяток коэффициентов, а человеку нужен один ответ на вопрос «есть ли связь».
    # Хранится именно сила связи, а не имя переменной: сравнивать нужно числа.
    best_any: tuple[float, str, str, int, float, float] | None = None
    best_significant: tuple[float, str, str, int, float, float] | None = None
    pairs = 0
    for i, first_name in enumerate(names):
        for j, second_name in enumerate(names):
            if j <= i:
                continue
            n, r, p = matrix[(i, j)]
            if not (isinstance(r, float) and math.isfinite(r)):
                continue
            pairs += 1
            candidate = (
                abs(r), str(first_name), str(second_name), int(n), float(r), float(p)
            )
            if best_any is None or candidate[0] > best_any[0]:
                best_any = candidate
            if math.isfinite(p) and p < 0.05:
                if best_significant is None or candidate[0] > best_significant[0]:
                    best_significant = candidate

    # Значимая связь интереснее сильной: сильная, но случайная ничего не значит.
    chosen = best_significant or best_any
    if chosen is not None:
        _strength, first_name, second_name, n, r, p = chosen
        result.add_findings(
            interpretation.correlation(
                # Без технического имени в скобках: в человеческой фразе оно лишнее.
                first=dataset.var(first_name).label or first_name,
                second=dataset.var(second_name).label or second_name,
                coefficient=float(r),
                p_value=float(p),
                n=int(n),
                method=command.method,
            )
        )
        if pairs > 1:
            result.explain(
                f"Проверено пар переменных: {pairs}. В выводе — "
                + (
                    "самая сильная из значимых связей."
                    if best_significant is not None
                    else "самая сильная связь, но и она статистически незначима: "
                    "связи между этими показателями в данных не видно."
                )
            )

    return result


__all__ = ["METHOD_LABELS", "run"]

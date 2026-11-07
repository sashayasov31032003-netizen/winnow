"""t-критерий: одна выборка, независимые и связанные выборки.

Отдельно считаются размеры эффекта (d Коэна, g Хеджеса). В SPSS их нет "из
коробки", а именно их всё чаще требуют журналы, - поэтому это осмысленное
преимущество, а не просто ещё одна таблица.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import CommandError, TTestCommand
from winnow.stats.common import cohens_d_pooled, group_stats, hedges_g, t_ci, valid_values
from winnow.stats.result import Column, Result, Table


def levene_test(groups: list[np.ndarray]) -> tuple[float, float, float]:
    """Тест Ливиня на равенство дисперсий (вариант Брауна-Форсайта, центр - медиана).

    Ключевая тонкость: каждая выборка центрируется по СВОЕЙ медиане, а не по
    общей медиане всех данных. Если центрировать по общей медиане, статистика
    получается совсем другой - эта ошибка и была допущена сначала.

    Реализация сознательно повторяет scipy.stats.levene(center="median"), чтобы
    числа в отчёте совпадали с эталоном, к которому пользователь может обратиться.
    """
    groups = [g for g in groups if g.size > 0]
    k = len(groups)
    if k < 2:
        return float("nan"), float("nan"), float("nan")

    # Отклонения от медианы своей группы.
    z_groups = [np.abs(g - float(np.median(g))) for g in groups]

    sizes = np.array([g.size for g in z_groups], dtype=float)
    n_total = float(sizes.sum())
    means = np.array([float(np.mean(g)) for g in z_groups], dtype=float)

    # Общее среднее взвешивается по размерам групп.
    grand_mean = float(np.average(means, weights=sizes))
    between = float(np.sum(sizes * (means - grand_mean) ** 2))
    within_sum = float(np.sum([np.sum((z - means[i]) ** 2) for i, z in enumerate(z_groups)]))

    df1 = float(k - 1)
    df2 = float(n_total - k)
    if within_sum <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan"), df1, float("nan")

    # F = df2 * sum(n_i (Z_i. - Z..)^2) / sum_ij (Z_ij - Z_i.)^2
    f_value = (df2 * between) / within_sum
    return f_value, df1, float(sps.f.sf(f_value, df1, df2))


def _group_statistics_table(name: str, groups: list[tuple[str, np.ndarray]]) -> Table:
    table = Table(
        title=f"Статистики групп: {name}",
        columns=[
            Column("Группа", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Среднее", decimals=2),
            Column("Стд. отклонение", decimals=2),
            Column("Стд. ошибка среднего", decimals=2),
        ],
    )
    for label, values in groups:
        stats = group_stats(values)
        table.add_row([label, stats.n, stats.mean, stats.std, stats.sem])
    return table


def _independent_samples_table(
    name: str, first: np.ndarray, second: np.ndarray, confidence: float
) -> tuple[Table, dict[str, Any]]:
    summary: dict[str, Any] = {
        "n1": int(first.size),
        "n2": int(second.size),
        "mean1": float(np.mean(first)) if first.size else float("nan"),
        "mean2": float(np.mean(second)) if second.size else float("nan"),
        "std1": float(np.std(first, ddof=1)) if first.size > 1 else float("nan"),
        "std2": float(np.std(second, ddof=1)) if second.size > 1 else float("nan"),
    }

    table = Table(
        title=f"Критерий для независимых выборок: {name}",
        columns=[
            Column("", align="left", is_metric=False),
            Column("F Ливиня", decimals=3),
            Column("Зн. Ливиня", decimals=3),
            Column("t", decimals=3),
            Column("ст. св.", decimals=3),
            Column("знач. (2-стор.)", decimals=3),
            Column("Разность средних", decimals=3),
            Column("Стд. ошибка разности", decimals=3),
            Column("Нижняя", decimals=3),
            Column("Верхняя", decimals=3),
        ],
    )

    f_value, _df1, levene_p = levene_test([first, second])
    summary["levene_f"] = f_value
    summary["levene_p"] = levene_p
    equal_variances = not (math.isfinite(levene_p) and levene_p < 0.05)

    if first.size < 2 or second.size < 2:
        table.add_row([".", f_value, levene_p, None, None, None, None, None, None, None])
        summary["computed"] = False
        return table, summary

    mean_diff = summary["mean1"] - summary["mean2"]

    # Вариант с равными дисперсиями (объединённая оценка).
    pooled_var = (
        (first.size - 1) * summary["std1"] ** 2 + (second.size - 1) * summary["std2"] ** 2
    ) / (first.size + second.size - 2)
    pooled_se = (
        math.sqrt(pooled_var * (1.0 / first.size + 1.0 / second.size))
        if pooled_var > 0
        else float("nan")
    )
    df_pooled = float(first.size + second.size - 2)
    t_pooled = mean_diff / pooled_se if pooled_se and math.isfinite(pooled_se) else float("nan")

    # Вариант Уэлча (дисперсии не предполагаются равными).
    var1 = summary["std1"] ** 2 / first.size
    var2 = summary["std2"] ** 2 / second.size
    welch_se = math.sqrt(var1 + var2) if (var1 + var2) > 0 else float("nan")
    t_welch = mean_diff / welch_se if welch_se and math.isfinite(welch_se) else float("nan")
    if var1 + var2 > 0:
        df_welch = (var1 + var2) ** 2 / (
            var1**2 / (first.size - 1) + var2**2 / (second.size - 1)
        )
    else:
        df_welch = float("nan")

    rows = [
        ("Равные дисперсии приняты", t_pooled, df_pooled, pooled_se),
        ("Равные дисперсии не приняты", t_welch, df_welch, welch_se),
    ]
    for i, (label, t_value, df_value, se) in enumerate(rows):
        p_value = (
            2.0 * float(sps.t.sf(abs(t_value), df_value))
            if math.isfinite(t_value) and df_value > 0
            else float("nan")
        )
        if math.isfinite(se) and math.isfinite(df_value) and df_value > 0:
            critical = float(sps.t.ppf(1.0 - (1.0 - confidence) / 2.0, df_value))
            low, high = mean_diff - critical * se, mean_diff + critical * se
        else:
            low = high = float("nan")
        table.add_row(
            [
                label,
                f_value if i == 0 else None,
                levene_p if i == 0 else None,
                t_value,
                df_value,
                p_value,
                mean_diff,
                se,
                low,
                high,
            ]
        )
        if i == 0:
            summary.update({"t_pooled": t_value, "df_pooled": df_pooled, "p_pooled": p_value})
        else:
            summary.update({"t_welch": t_value, "df_welch": df_welch, "p_welch": p_value})

    summary["computed"] = True
    summary["mean_diff"] = mean_diff
    summary["equal_variances"] = equal_variances
    table.footnote(f"Доверительный интервал разности средних: {confidence * 100:.1f}%.")
    if math.isfinite(levene_p):
        if equal_variances:
            table.footnote("Тест Ливиня незначим - используйте строку с равными дисперсиями.")
        else:
            table.footnote("Тест Ливиня значим - используйте строку с неравными дисперсиями (Уэлч).")
    return table, summary


def _not_normal(sample: np.ndarray) -> bool:
    """Отличается ли распределение от нормального (Шапиро-Уилк).

    Проверка применяется осторожно: при малом числе наблюдений критерий почти
    всегда незначим, а при большом - ловит ничтожные отклонения. Поэтому нужен и
    минимум наблюдений, и достаточное число различных значений.
    """
    if sample.size < 8 or len(np.unique(sample)) < 4:
        return False
    try:
        _statistic, p_value = sps.shapiro(sample.astype(float))
    except (ValueError, TypeError):
        return False
    return bool(math.isfinite(p_value) and p_value < 0.05)


def _interpret_d(value: float) -> str:
    if value is None or not math.isfinite(value):
        return "."
    magnitude = abs(value)
    if magnitude < 0.2:
        return "ниже малого"
    if magnitude < 0.5:
        return "малый"
    if magnitude < 0.8:
        return "средний"
    return "большой"


def _effect_size_table(d: float, g: float, note: str) -> Table:
    table = Table(
        title="Размеры эффекта",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
            Column("Интерпретация", align="left", is_metric=False),
        ],
    )
    table.add_row(["d Коэна", d, _interpret_d(d)])
    table.add_row(["g Хеджеса (поправка на смещение)", g, _interpret_d(g)])
    table.footnote(note)
    table.footnote("Ориентиры: 0.20 - малый, 0.50 - средний, 0.80 - большой эффект.")
    return table


def _hedges_from_d(d_value: float, df: float) -> float:
    if not math.isfinite(d_value) or df <= 1:
        return float("nan")
    return d_value * (1.0 - 3.0 / (4.0 * df - 1.0))


def _independent(command: TTestCommand, result: Result, frame: pd.DataFrame) -> None:
    dataset = command.dataset
    group_series = pd.to_numeric(frame[command.group_var], errors="coerce")
    group_meta = dataset.var(command.group_var)
    values = [float(v) for v in command.group_values]

    for name in command.test_vars:
        series = pd.to_numeric(frame[name], errors="coerce")
        groups: list[tuple[str, np.ndarray]] = []
        for value in values:
            mask = (group_series == value).to_numpy()
            groups.append((group_meta.label_for(value), valid_values(series[mask])))

        result.add_table(_group_statistics_table(name, groups))

        first, second = groups[0][1], groups[1][1]
        if first.size == 0 or second.size == 0:
            result.warn(
                f"{name}: одна из групп пуста - критерий не вычислен "
                f"(группы: {values[0]:g}, {values[1]:g})"
            )
            continue
        if first.size < 2 or second.size < 2:
            result.warn(
                f"{name}: в группе меньше двух валидных наблюдений - критерий не вычислен"
            )
            continue

        table, summary = _independent_samples_table(name, first, second, command.confidence)
        result.add_table(table)

        effect = None
        if command.effect_size and summary.get("computed"):
            d_value = cohens_d_pooled(
                summary["mean1"], summary["std1"], summary["n1"],
                summary["mean2"], summary["std2"], summary["n2"],
            )
            g_value = hedges_g(d_value, summary["n1"], summary["n2"])
            effect = d_value
            result.add_table(
                _effect_size_table(
                    d_value,
                    g_value,
                    f"{name}: разность средних (группа 1 - группа 2), "
                    "объединённое стд. отклонение.",
                )
            )

        # Вывод «простыми словами»: числа те же, что в таблицах, но сказано, что
        # из них следует. Значимость берётся из той строки, которую нужно читать:
        # при разных дисперсиях это поправка Уэлча.
        if summary.get("computed"):
            welch = not summary.get("equal_variances", True)
            p_value = summary["p_welch"] if welch else summary["p_pooled"]
            result.add_findings(
                interpretation.compare_two_groups(
                    outcome=dataset.var(name).label or name,
                    group1=groups[0][0],
                    group2=groups[1][0],
                    n1=int(summary["n1"]),
                    n2=int(summary["n2"]),
                    mean1=float(summary["mean1"]),
                    mean2=float(summary["mean2"]),
                    p_value=float(p_value),
                    effect=float(effect) if effect is not None else None,
                    welch=welch,
                )
            )
            # Проверка применимости с советом: критерий Стьюдента предполагает
            # нормальность, и если её нет, нужно назвать подходящую замену.
            non_normal = [
                label
                for label, sample in ((groups[0][0], first), (groups[1][0], second))
                if _not_normal(sample)
            ]
            result.add_findings(
                interpretation.normality_caution(
                    outcome=dataset.var(name).label or name,
                    groups=non_normal,
                    alternative="критерий Манна-Уитни (меню «Анализ → "
                    "Непараметрические критерии»)",
                )
            )


def _paired(command: TTestCommand, result: Result, frame: pd.DataFrame) -> None:
    for first_name, second_name in zip(command.test_vars, command.pair_with):
        pair_label = f"{first_name} - {second_name}"
        first = pd.to_numeric(frame[first_name], errors="coerce")
        second = pd.to_numeric(frame[second_name], errors="coerce")
        mask = first.notna() & second.notna()
        a = first[mask].to_numpy(dtype=float)
        b = second[mask].to_numpy(dtype=float)

        if a.size < 2:
            result.warn(f"{pair_label}: меньше двух полных пар - критерий не вычислен")
            continue

        std_a = float(np.std(a, ddof=1))
        std_b = float(np.std(b, ddof=1))
        stats_table = Table(
            title=f"Статистики парных выборок: {pair_label}",
            columns=[
                Column("", align="left", is_metric=False),
                Column("Среднее", decimals=2),
                Column("N", decimals=0),
                Column("Стд. отклонение", decimals=2),
                Column("Стд. ошибка среднего", decimals=2),
            ],
        )
        stats_table.add_row(
            [first_name, float(np.mean(a)), int(a.size), std_a, std_a / math.sqrt(a.size)]
        )
        stats_table.add_row(
            [second_name, float(np.mean(b)), int(b.size), std_b, std_b / math.sqrt(b.size)]
        )
        result.add_table(stats_table)

        if a.size > 2 and std_a > 0 and std_b > 0:
            r_value, r_p = sps.pearsonr(a, b)
            corr_table = Table(
                title=f"Парные корреляции: {pair_label}",
                columns=[
                    Column("", align="left", is_metric=False),
                    Column("N", decimals=0),
                    Column("Корреляция", decimals=3),
                    Column("знач.", decimals=3),
                ],
            )
            corr_table.add_row([pair_label, int(a.size), float(r_value), float(r_p)])
            result.add_table(corr_table)

        diff = a - b
        n = int(diff.size)
        mean_diff = float(np.mean(diff))
        std_diff = float(np.std(diff, ddof=1))
        se_diff = std_diff / math.sqrt(n)
        t_value = mean_diff / se_diff if se_diff > 0 else float("nan")
        df_value = float(n - 1)
        p_value = (
            2.0 * float(sps.t.sf(abs(t_value), df_value))
            if math.isfinite(t_value)
            else float("nan")
        )
        low, high = t_ci(mean_diff, std_diff, n, command.confidence)

        diff_table = Table(
            title=f"Критерий для парных выборок: {pair_label}",
            columns=[
                Column("", align="left", is_metric=False),
                Column("Среднее", decimals=3),
                Column("Стд. отклонение", decimals=3),
                Column("Стд. ошибка среднего", decimals=3),
                Column("Нижняя", decimals=3),
                Column("Верхняя", decimals=3),
                Column("t", decimals=3),
                Column("ст. св.", decimals=0),
                Column("знач. (2-стор.)", decimals=3),
            ],
        )
        diff_table.add_row(
            [pair_label, mean_diff, std_diff, se_diff, low, high, t_value, df_value, p_value]
        )
        diff_table.footnote(f"Доверительный интервал разности: {command.confidence * 100:.1f}%.")
        result.add_table(diff_table)

        if command.effect_size and std_diff > 0:
            d_value = mean_diff / std_diff
            result.add_table(
                _effect_size_table(
                    d_value,
                    _hedges_from_d(d_value, df_value),
                    f"{pair_label}: d для парных выборок "
                    "(средняя разность / стд. отклонение разности).",
                )
            )


def _one_sample(command: TTestCommand, result: Result, frame: pd.DataFrame) -> None:
    for name in command.test_vars:
        values = valid_values(pd.to_numeric(frame[name], errors="coerce"))
        if values.size < 2:
            result.warn(f"{name}: меньше двух валидных наблюдений - критерий не вычислен")
            continue

        n = int(values.size)
        mean = float(np.mean(values))
        std = float(np.std(values, ddof=1))
        sem = std / math.sqrt(n)
        df_value = float(n - 1)
        t_value = (mean - command.test_value) / sem if sem > 0 else float("nan")
        p_value = (
            2.0 * float(sps.t.sf(abs(t_value), df_value))
            if math.isfinite(t_value)
            else float("nan")
        )
        low, high = t_ci(mean, std, n, command.confidence)

        table = Table(
            title=f"Критерий для одной выборки: {name}",
            columns=[
                Column("", align="left", is_metric=False),
                Column("N", decimals=0),
                Column("Среднее", decimals=3),
                Column("Стд. отклонение", decimals=3),
                Column("Стд. ошибка среднего", decimals=3),
                Column("Нижняя", decimals=3),
                Column("Верхняя", decimals=3),
                Column("t", decimals=3),
                Column("ст. св.", decimals=0),
                Column("знач. (2-стор.)", decimals=3),
            ],
        )
        table.add_row([name, n, mean, std, sem, low, high, t_value, df_value, p_value])
        table.footnote(f"Проверяемое значение: {command.test_value:g}")
        table.footnote(f"Доверительный интервал среднего: {command.confidence * 100:.1f}%.")
        result.add_table(table)

        if command.effect_size and std > 0:
            d_value = (mean - command.test_value) / std
            result.add_table(
                _effect_size_table(
                    d_value,
                    _hedges_from_d(d_value, df_value),
                    f"{name}: d для одной выборки "
                    f"(отклонение от {command.test_value:g} в стд. отклонениях).",
                )
            )


def run(command: TTestCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    if dataset.weight_values() is not None:
        result.note(f"Учтены веса кейсов: {dataset.weight_var}")

    names = list(command.test_vars) + list(command.pair_with)
    if command.group_var:
        names.append(command.group_var)
    frame = dataset.analysis_frame(names)

    if command.kind == "independent":
        _independent(command, result, frame)
    elif command.kind == "paired":
        _paired(command, result, frame)
    else:
        _one_sample(command, result, frame)

    return result


__all__ = ["levene_test", "run"]

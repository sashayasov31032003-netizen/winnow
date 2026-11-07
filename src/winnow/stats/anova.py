"""Однофакторный дисперсионный анализ (ANOVA).

Зачем это нужно: сравнивать три группы и более t-критерием нельзя - при
многократных сравнениях резко растёт вероятность ложного срабатывания. ANOVA
проверяет гипотезу о равенстве всех средних сразу, а апостериорные сравнения
показывают, какие именно группы различаются, с поправкой на множественность.

Числа сверены с независимыми эталонами: F и значимость - с scipy, апостериорные
сравнения - с распределением стьюдентизированного размаха (критерий Тьюки).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import AnovaCommand, CommandError
from winnow.stats.common import (
    bonferroni_adjust,
    eta_squared,
    holm_adjust,
    omega_squared,
    t_ci,
    tukey_critical_q,
    tukey_p_value,
    valid_values,
)
from winnow.stats.result import Column, Result, Table
from winnow.stats.ttest import levene_test

POST_HOC_LABELS = {
    "tukey": "Тьюки (HSD)",
    "bonferroni": "Бонферрони",
    "holm": "Холм",
    "none": "не считать",
}


@dataclass
class GroupData:
    """Сгруппированные наблюдения по одному уровню фактора."""

    label: str
    values: np.ndarray

    @property
    def n(self) -> int:
        return int(self.values.size)

    @property
    def mean(self) -> float:
        return float(np.mean(self.values)) if self.n else float("nan")

    @property
    def std(self) -> float:
        return float(np.std(self.values, ddof=1)) if self.n > 1 else float("nan")

    @property
    def sem(self) -> float:
        std = self.std
        return std / math.sqrt(self.n) if self.n > 1 and math.isfinite(std) else float("nan")


def split_groups(dataset, dependent: str, factor: str) -> list[GroupData]:
    """Разбивает зависимую переменную на группы по уровням фактора."""
    factor_var = dataset.var(factor)
    frame = dataset.analysis_frame([dependent, factor])
    groups: list[GroupData] = []

    from winnow.stats.common import category_label, ordered_categories

    for value in ordered_categories(frame[factor], factor_var.value_labels):
        mask = (frame[factor] == value).to_numpy()
        values = valid_values(pd.to_numeric(frame[dependent][mask], errors="coerce"))
        if values.size == 0:
            continue
        groups.append(GroupData(category_label(value, factor_var.value_labels), values))
    return groups


def anova_table(groups: list[GroupData]) -> dict[str, float]:
    """Классическая таблица ANOVA: суммы квадратов, F и значимость."""
    k = len(groups)
    n_total = sum(group.n for group in groups)
    all_values = np.concatenate([group.values for group in groups])
    grand_mean = float(np.mean(all_values))

    ss_between = sum(group.n * (group.mean - grand_mean) ** 2 for group in groups)
    ss_within = sum(float(np.sum((group.values - group.mean) ** 2)) for group in groups)
    ss_total = ss_between + ss_within

    df_between = float(k - 1)
    df_within = float(n_total - k)
    ms_between = ss_between / df_between if df_between > 0 else float("nan")
    ms_within = ss_within / df_within if df_within > 0 else float("nan")
    f_value = ms_between / ms_within if ms_within and ms_within > 0 else float("nan")
    p_value = float(sps.f.sf(f_value, df_between, df_within)) if math.isfinite(f_value) else float("nan")

    return {
        "ss_between": ss_between,
        "ss_within": ss_within,
        "ss_total": ss_total,
        "df_between": df_between,
        "df_within": df_within,
        "ms_between": ms_between,
        "ms_within": ms_within,
        "f": f_value,
        "p": p_value,
        "n_total": float(n_total),
        "k": float(k),
        "grand_mean": grand_mean,
    }


def welch_anova(groups: list[GroupData]) -> dict[str, float]:
    """Робастный тест Уэлча: ANOVA без предположения о равенстве дисперсий.

    Если тест Ливиня значим, обычный F-критерий ненадёжен, и SPSS предлагает
    именно этот вариант. Формула: веса обратно пропорциональны дисперсии группы.
    """
    empty = {"f": float("nan"), "df1": float("nan"), "df2": float("nan"), "p": float("nan")}
    k = len(groups)
    if k < 2:
        return empty
    if any(group.n < 2 or not math.isfinite(group.std) or group.std <= 0 for group in groups):
        return empty

    sizes = np.array([group.n for group in groups], dtype=float)
    variances = np.array([group.std**2 for group in groups], dtype=float)
    means = np.array([group.mean for group in groups], dtype=float)

    weights = sizes / variances
    weight_sum = float(weights.sum())
    if not math.isfinite(weight_sum) or weight_sum <= 0:
        return empty

    weighted_mean = float(np.sum(weights * means) / weight_sum)
    # Лямбда - мера неравенства дисперсий; при равных дисперсиях она равна нулю,
    # и знаменатель обращается в единицу (обычный ANOVA).
    correction_terms = (1.0 - weights / weight_sum) ** 2 / (sizes - 1.0)
    lam = float(np.sum(correction_terms))

    numerator = float(np.sum(weights * (means - weighted_mean) ** 2)) / (k - 1)
    denominator = 1.0 + (2.0 * (k - 2) / (k**2 - 1.0)) * lam
    f_value = numerator / denominator

    df1 = float(k - 1)
    df2 = 1.0 / ((3.0 / (k**2 - 1.0)) * lam) if lam > 0 else float("nan")
    p_value = (
        float(sps.f.sf(f_value, df1, df2))
        if math.isfinite(f_value) and math.isfinite(df2) and df2 > 0
        else float("nan")
    )
    return {"f": f_value, "df1": df1, "df2": df2, "p": p_value}


def post_hoc_comparisons(
    groups: list[GroupData], stats_table: dict[str, float], method: str, confidence: float
) -> list[dict[str, Any]]:
    """Парные сравнения групп с поправкой на множественность.

    Для Тьюки используется распределение стьюдентизированного размаха (так же,
    как в SPSS), для Бонферрони и Холма - обычные парные t-критерии с общей
    оценкой дисперсии и последующей поправкой значимости.
    """
    if method == "none" or len(groups) < 2:
        return []

    k = len(groups)
    df_within = stats_table["df_within"]
    ms_within = stats_table["ms_within"]
    alpha = 1.0 - confidence

    rows: list[dict[str, Any]] = []
    for i in range(k):
        for j in range(i + 1, k):
            first, second = groups[i], groups[j]
            difference = first.mean - second.mean
            se = math.sqrt(ms_within * (1.0 / first.n + 1.0 / second.n)) if ms_within > 0 else float("nan")

            if method == "tukey":
                q_value = abs(difference) / se if se and math.isfinite(se) else float("nan")
                p_value = tukey_p_value(q_value, k, df_within)
                critical = tukey_critical_q(confidence, k, df_within)
                margin = critical * se if math.isfinite(critical) and math.isfinite(se) else float("nan")
                low, high = difference - margin, difference + margin
            else:
                t_value = difference / se if se and math.isfinite(se) else float("nan")
                p_value = (
                    2.0 * float(sps.t.sf(abs(t_value), df_within))
                    if math.isfinite(t_value) and df_within > 0
                    else float("nan")
                )
                critical = (
                    float(sps.t.ppf(1.0 - alpha / 2.0, df_within)) if df_within > 0 else float("nan")
                )
                margin = critical * se if math.isfinite(critical) and math.isfinite(se) else float("nan")
                low, high = difference - margin, difference + margin

            rows.append(
                {
                    "group1": first.label,
                    "group2": second.label,
                    "difference": difference,
                    "se": se,
                    "p_raw": p_value,
                    "low": low,
                    "high": high,
                    "n1": first.n,
                    "n2": second.n,
                }
            )

    if method in ("bonferroni", "holm"):
        raw = [row["p_raw"] for row in rows]
        adjusted = bonferroni_adjust(raw) if method == "bonferroni" else holm_adjust(raw)
        for row, value in zip(rows, adjusted):
            row["p"] = value
    else:
        for row in rows:
            row["p"] = row["p_raw"]
    return rows


def _descriptives_table(dependent_name: str, groups: list[GroupData], confidence: float) -> Table:
    table = Table(
        title=f"Описательные статистики: {dependent_name}",
        columns=[
            Column("Группа", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Среднее", decimals=3),
            Column("Стд. отклонение", decimals=3),
            Column("Стд. ошибка", decimals=3),
            Column("Нижняя граница", decimals=3),
            Column("Верхняя граница", decimals=3),
            Column("Минимум", decimals=3),
            Column("Максимум", decimals=3),
        ],
    )
    for group in groups:
        low, high = t_ci(group.mean, group.std, group.n, confidence)
        table.add_row(
            [
                group.label,
                group.n,
                group.mean,
                group.std,
                group.sem,
                low,
                high,
                float(np.min(group.values)),
                float(np.max(group.values)),
            ]
        )
    total_values = np.concatenate([group.values for group in groups])
    total_mean = float(np.mean(total_values))
    total_std = float(np.std(total_values, ddof=1)) if total_values.size > 1 else float("nan")
    low, high = t_ci(total_mean, total_std, int(total_values.size), confidence)
    table.add_row(
        [
            "Всего",
            int(total_values.size),
            total_mean,
            total_std,
            total_std / math.sqrt(total_values.size) if total_values.size > 1 else float("nan"),
            low,
            high,
            float(np.min(total_values)),
            float(np.max(total_values)),
        ]
    )
    table.footnote(f"Доверительные интервалы для среднего: {confidence * 100:.1f}%.")
    return table


def _homogeneity_table(groups: list[GroupData]) -> Table | None:
    if len(groups) < 2:
        return None
    f_value, df1, p_value = levene_test([group.values for group in groups])
    table = Table(
        title="Проверка однородности дисперсий",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Статистика Ливиня", decimals=3),
            Column("ст. св. 1", decimals=0),
            Column("ст. св. 2", decimals=0),
            Column("знач.", decimals=3),
        ],
    )
    df2 = float(sum(group.n for group in groups) - len(groups))
    table.add_row(["По медиане", f_value, df1, df2, p_value])
    table.footnote(
        "Нулевая гипотеза: дисперсии групп равны. Значимость меньше 0.05 означает "
        "неравные дисперсии - тогда используйте робастный тест Уэлча."
    )
    return table


def _anova_main_table(stats_table: dict[str, float], dependent_name: str) -> Table:
    table = Table(
        title=f"Однофакторный ANOVA: {dependent_name}",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Сумма квадратов", decimals=3),
            Column("ст. св.", decimals=0),
            Column("Средний квадрат", decimals=3),
            Column("F", decimals=3),
            Column("знач.", decimals=3),
        ],
    )
    table.add_row(
        [
            "Между группами",
            stats_table["ss_between"],
            stats_table["df_between"],
            stats_table["ms_between"],
            stats_table["f"],
            stats_table["p"],
        ]
    )
    table.add_row(
        [
            "Внутри групп",
            stats_table["ss_within"],
            stats_table["df_within"],
            stats_table["ms_within"],
            None,
            None,
        ]
    )
    table.add_row(
        [
            "Всего",
            stats_table["ss_total"],
            stats_table["df_between"] + stats_table["df_within"],
            None,
            None,
            None,
        ]
    )
    table.footnote(
        "Нулевая гипотеза: средние всех групп равны. Значимость меньше 0.05 "
        "означает, что хотя бы одна группа отличается."
    )
    return table


def _welch_table(values: dict[str, float]) -> Table:
    table = Table(
        title="Робастный тест равенства средних (Уэлч)",
        columns=[
            Column("", align="left", is_metric=False),
            Column("Статистика", decimals=3),
            Column("ст. св. 1", decimals=3),
            Column("ст. св. 2", decimals=3),
            Column("знач.", decimals=3),
        ],
    )
    table.add_row(["Уэлч", values["f"], values["df1"], values["df2"], values["p"]])
    table.footnote("Применяется, когда дисперсии групп не равны (тест Ливиня значим).")
    return table


def _effect_size_table(stats_table: dict[str, float]) -> Table:
    eta = eta_squared(stats_table["ss_between"], stats_table["ss_total"])
    omega = omega_squared(stats_table["ss_between"], stats_table["ss_within"], stats_table["ms_within"])
    table = Table(
        title="Размеры эффекта",
        columns=[
            Column("Показатель", align="left", is_metric=False),
            Column("Значение", decimals=3),
            Column("Интерпретация", align="left", is_metric=False),
        ],
    )
    table.add_row(["Эта-квадрат (доля объяснённой дисперсии)", eta, _interpret_eta(eta)])
    table.add_row(["Омега-квадрат (несмещённая оценка)", omega, _interpret_eta(omega)])
    table.footnote("Ориентиры: 0.01 - малый, 0.06 - средний, 0.14 - большой эффект.")
    return table


def _interpret_eta(value: float) -> str:
    if value is None or not math.isfinite(value):
        return "."
    if value < 0.01:
        return "ниже малого"
    if value < 0.06:
        return "малый"
    if value < 0.14:
        return "средний"
    return "большой"


def _post_hoc_table(
    rows: list[dict[str, Any]], method: str, confidence: float
) -> Table:
    table = Table(
        title=f"Апостериорные сравнения ({POST_HOC_LABELS.get(method, method)})",
        columns=[
            Column("Группа 1", align="left", is_metric=False),
            Column("Группа 2", align="left", is_metric=False),
            Column("Разность средних", decimals=3),
            Column("Стд. ошибка", decimals=3),
            Column("знач.", decimals=3),
            Column("Нижняя граница", decimals=3),
            Column("Верхняя граница", decimals=3),
        ],
    )
    for row in rows:
        table.add_row(
            [
                row["group1"],
                row["group2"],
                row["difference"],
                row["se"],
                row["p"],
                row["low"],
                row["high"],
            ]
        )
    table.footnote(f"Доверительные интервалы разностей: {confidence * 100:.1f}%.")
    if method in ("bonferroni", "holm"):
        table.footnote("Значимость скорректирована на множественные сравнения.")
    else:
        table.footnote(
            "Значимость рассчитана по распределению стьюдентизированного размаха "
            "(критерий Тьюки), поправка на множественность уже учтена."
        )
    return table


def _homogeneous_subsets(groups: list[GroupData], stats_table: dict[str, float], confidence: float) -> Table | None:
    """Однородные подмножества: группы, между которыми нет значимых различий.

    Полезно тем, что сразу показывает «блоки» похожих групп, без чтения всех
    парных сравнений.
    """
    if len(groups) < 2:
        return None

    ordered = sorted(groups, key=lambda group: group.mean)
    df_within = stats_table["df_within"]
    ms_within = stats_table["ms_within"]
    k = len(groups)
    critical = tukey_critical_q(confidence, k, df_within)
    if not math.isfinite(critical) or ms_within <= 0:
        return None

    subsets: list[list[GroupData]] = []
    current: list[GroupData] = []
    for group in ordered:
        if not current:
            current = [group]
            continue
        significant = False
        for other in current:
            se = math.sqrt(ms_within * (1.0 / group.n + 1.0 / other.n))
            if abs(group.mean - other.mean) / se > critical:
                significant = True
                break
        if significant:
            subsets.append(current)
            current = [group]
        else:
            current.append(group)
    if current:
        subsets.append(current)

    table = Table(
        title="Однородные подмножества (Тьюки)",
        columns=[Column(f"Подмножество {index + 1}", decimals=3) for index in range(len(subsets))],
        footnotes=[
            "В одном столбце - группы, средние которых значимо не различаются.",
            f"Уровень значимости: {1 - confidence:.3f}.",
        ],
    )
    max_rows = max(len(subset) for subset in subsets)
    for index in range(max_rows):
        row: list[Any] = []
        for subset in subsets:
            if index < len(subset):
                group = subset[index]
                row.append(f"{group.label}: {group.mean:.3f}")
            else:
                row.append("")
        table.add_row(row)
    return table


def run(command: AnovaCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    factor_var = dataset.var(command.factor)
    factor_name = factor_var.display_name

    for dependent in command.dependent:
        dependent_name = dataset.var(dependent).display_name
        groups = split_groups(dataset, dependent, command.factor)

        if len(groups) < 2:
            result.warn(
                f"{dependent_name}: групп с данными меньше двух - ANOVA невозможен"
            )
            continue
        small = [group for group in groups if group.n < 2]
        if small:
            result.warn(
                f"{dependent_name}: в группах "
                + ", ".join(f"{group.label} (N={group.n})" for group in small)
                + " меньше двух наблюдений - дисперсия не определена"
            )
        total_n = sum(group.n for group in groups)
        if total_n <= len(groups):
            result.warn(f"{dependent_name}: слишком мало наблюдений для ANOVA")
            continue

        if command.descriptives:
            result.add_table(_descriptives_table(dependent_name, groups, command.confidence))

        if command.homogeneity:
            homogeneity = _homogeneity_table(groups)
            if homogeneity is not None:
                result.add_table(homogeneity)

        stats_table = anova_table(groups)
        result.add_table(_anova_main_table(stats_table, dependent_name))

        if math.isfinite(stats_table["p"]):
            result.note(
                f"{dependent_name}: F({stats_table['df_between']:.0f}, "
                f"{stats_table['df_within']:.0f}) = {stats_table['f']:.3f}, "
                f"p = {stats_table['p']:.3f}"
            )

        if command.welch:
            result.add_table(_welch_table(welch_anova(groups)))

        if command.effect_size:
            result.add_table(_effect_size_table(stats_table))

        if command.post_hoc != "none":
            rows = post_hoc_comparisons(groups, stats_table, command.post_hoc, command.confidence)
            if rows:
                result.add_table(_post_hoc_table(rows, command.post_hoc, command.confidence))
            subsets = _homogeneous_subsets(groups, stats_table, command.confidence)
            if subsets is not None:
                result.add_table(subsets)

        # Вывод «простыми словами»: что следует из F и p, между какими группами
        # разница, и какова доля объяснённой дисперсии.
        if math.isfinite(stats_table["p"]):
            usable = [group for group in groups if group.n >= 2]
            extremes = None
            if usable:
                highest = max(usable, key=lambda group: group.mean)
                lowest = min(usable, key=lambda group: group.mean)
                extremes = (highest.label, highest.mean, lowest.label, lowest.mean)
            eta = eta_squared(stats_table["ss_between"], stats_table["ss_total"])
            result.add_findings(
                interpretation.compare_several_groups(
                    outcome=dataset.var(dependent).label or dependent,
                    factor=dataset.var(command.factor).label or command.factor,
                    group_count=len(groups),
                    n=total_n,
                    f_value=float(stats_table["f"]),
                    df_between=float(stats_table["df_between"]),
                    df_within=float(stats_table["df_within"]),
                    p_value=float(stats_table["p"]),
                    eta_squared=float(eta) if math.isfinite(eta) else None,
                    extremes=extremes,
                )
            )
            # Совет по применимости: при разных дисперсиях обычный F ненадёжен.
            if len(groups) >= 2:
                _f, _df, levene_p = levene_test([group.values for group in groups])
                result.add_findings(
                    interpretation.variance_caution(
                        outcome=dataset.var(dependent).label or dependent,
                        levene_p=float(levene_p),
                        robust="робастный тест Уэлча (он есть в этом отчёте) или "
                        "критерий Краскела-Уоллиса среди непараметрических",
                    )
                )

        result.meta["factor"] = factor_name
        result.meta["dependent"] = dependent_name

    if result.is_empty:
        result.warn("Ни одной таблицы не построено")
    return result


__all__ = [
    "POST_HOC_LABELS",
    "GroupData",
    "anova_table",
    "post_hoc_comparisons",
    "run",
    "split_groups",
    "welch_anova",
]

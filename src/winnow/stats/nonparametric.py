"""Непараметрические критерии: Манна-Уитни, Краскела-Уоллиса, Уилкоксона, Фридмана.

Зачем это нужно: t-критерий и ANOVA требуют нормально распределённых данных.
На практике в дипломных выборках (маленькие группы, порядковые шкалы, выбросы)
это условие часто не выполняется, и тогда корректны именно эти критерии.

Числа сверяются со scipy: Манна-Уитни (с поправкой на связи), Краскела-Уоллиса,
Уилкоксона и Фридмана. Это важно, потому что разные программы считают
непараметрику по-разному (точный тест против асимптотики), и расхождение нужно
уметь объяснить.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.stats import interpretation
from winnow.stats.command import CommandError, NonparametricCommand
from winnow.stats.common import (
    bonferroni_adjust,
    epsilon_squared,
    holm_adjust,
    rank_biserial_from_u,
    valid_values,
)
from winnow.stats.result import Column, Result, Table

METHOD_LABELS = {
    "mann_whitney": "U Манна-Уитни",
    "kruskal_wallis": "H Краскела-Уоллиса",
    "wilcoxon": "T Уилкоксона",
    "friedman": "Хи-квадрат Фридмана",
}


@dataclass
class RankGroup:
    """Группа наблюдений с ранговой статистикой."""

    label: str
    values: np.ndarray
    mean_rank: float = float("nan")
    rank_sum: float = float("nan")
    n: int = 0

    def __post_init__(self) -> None:
        self.n = int(self.values.size)


def _rank_groups(groups: list[RankGroup]) -> None:
    """Считает средние ранги с учётом связей (одинаковые значения получают общий ранг)."""
    all_values = np.concatenate([group.values for group in groups]) if groups else np.array([])
    if all_values.size == 0:
        return
    ranks = sps.rankdata(all_values, method="average")
    position = 0
    for group in groups:
        size = group.n
        chunk = ranks[position : position + size]
        position += size
        group.mean_rank = float(np.mean(chunk)) if size else float("nan")
        group.rank_sum = float(np.sum(chunk)) if size else float("nan")


def _number_of_ties(groups: list[RankGroup]) -> int:
    """Число групп связанных рангов - нужно для поправки в критерии Манна-Уитни."""
    if not groups:
        return 0
    all_values = np.concatenate([group.values for group in groups])
    _, counts = np.unique(all_values, return_counts=True)
    return int(np.sum(counts > 1))


def _descriptives_table(dependent_name: str, groups: list[RankGroup]) -> Table:
    table = Table(
        title=f"Описательные статистики: {dependent_name}",
        columns=[
            Column("Группа", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Среднее", decimals=3),
            Column("Стд. отклонение", decimals=3),
            Column("Медиана", decimals=3),
            Column("Минимум", decimals=3),
            Column("Максимум", decimals=3),
        ],
    )
    for group in groups:
        values = group.values
        table.add_row(
            [
                group.label,
                group.n,
                float(np.mean(values)),
                float(np.std(values, ddof=1)) if group.n > 1 else float("nan"),
                float(np.median(values)),
                float(np.min(values)),
                float(np.max(values)),
            ]
        )
    return table


def _ranks_table(dependent_name: str, groups: list[RankGroup]) -> Table:
    table = Table(
        title=f"Ранги: {dependent_name}",
        columns=[
            Column("Группа", align="left", is_metric=False),
            Column("N", decimals=0),
            Column("Средний ранг", decimals=2),
            Column("Сумма рангов", decimals=2),
        ],
    )
    for group in groups:
        table.add_row([group.label, group.n, group.mean_rank, group.rank_sum])
    return table


def mann_whitney(groups: list[RankGroup]) -> dict[str, Any]:
    """Критерий Манна-Уитни для двух независимых выборок."""
    if len(groups) != 2:
        return {"applicable": False, "reason": "нужны ровно две группы"}
    first, second = groups
    if first.n < 1 or second.n < 1:
        return {"applicable": False, "reason": "одна из групп пуста"}

    result = sps.mannwhitneyu(first.values, second.values, alternative="two-sided")
    u_value = float(result.statistic)
    p_value = float(result.pvalue)
    n1, n2 = first.n, second.n
    # Рангово-бисериальная корреляция как размер эффекта: направление и величина.
    r_value = rank_biserial_from_u(u_value, n1, n2)
    return {
        "applicable": True,
        "u": u_value,
        "p": p_value,
        "n1": n1,
        "n2": n2,
        "rank_biserial": r_value,
        "ties": _number_of_ties(groups),
    }


def kruskal_wallis(groups: list[RankGroup]) -> dict[str, Any]:
    """Критерий Краскела-Уоллиса для нескольких независимых выборок."""
    usable = [group for group in groups if group.n > 0]
    if len(usable) < 2:
        return {"applicable": False, "reason": "нужно минимум две группы с данными"}

    result = sps.kruskal(*[group.values for group in usable])
    h_value = float(result.statistic)
    p_value = float(result.pvalue)
    n_total = sum(group.n for group in usable)
    df_value = float(len(usable) - 1)

    # Поправка на связи: scipy её уже учитывает в статистике, но для отчёта
    # полезно показать, были ли связи вообще.
    ties = _number_of_ties(usable)
    # Внимание: третьим аргументом идёт ЧИСЛО ГРУПП, а не число степеней свободы
    # (k - 1). Перепутать легко, а знаменатель от этого меняется.
    epsilon = epsilon_squared(h_value, n_total, len(usable))
    return {
        "applicable": True,
        "h": h_value,
        "df": df_value,
        "p": p_value,
        "n_total": n_total,
        "k": len(usable),
        "epsilon_squared": epsilon,
        "ties": ties,
    }


def pairwise_mann_whitney(
    groups: list[RankGroup], method: str
) -> list[dict[str, Any]]:
    """Парные сравнения после Краскела-Уоллиса с поправкой на множественность."""
    rows: list[dict[str, Any]] = []
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            first, second = groups[i], groups[j]
            if first.n < 1 or second.n < 1:
                continue
            result = sps.mannwhitneyu(first.values, second.values, alternative="two-sided")
            rows.append(
                {
                    "group1": first.label,
                    "group2": second.label,
                    "u": float(result.statistic),
                    "p_raw": float(result.pvalue),
                    "n1": first.n,
                    "n2": second.n,
                }
            )
    if not rows:
        return rows

    raw = [row["p_raw"] for row in rows]
    adjusted = bonferroni_adjust(raw) if method == "bonferroni" else holm_adjust(raw)
    for row, value in zip(rows, adjusted):
        row["p"] = value
    return rows


def wilcoxon_test(first: np.ndarray, second: np.ndarray) -> dict[str, Any]:
    """Критерий знаковых рангов Уилкоксона для двух связанных выборок."""
    if first.size != second.size or first.size < 2:
        return {"applicable": False, "reason": "нужны пары наблюдений (минимум две)"}
    differences = first - second
    nonzero = int(np.sum(differences != 0))
    if nonzero == 0:
        return {"applicable": False, "reason": "все разности равны нулю"}

    result = sps.wilcoxon(first, second, zero_method="wilcox", alternative="two-sided")
    positive = float(np.sum(differences[differences > 0]))
    negative = float(np.sum(-differences[differences < 0]))
    return {
        "applicable": True,
        "t": float(result.statistic),
        "p": float(result.pvalue),
        "n": int(first.size),
        "nonzero": nonzero,
        "positive_sum": positive,
        "negative_sum": negative,
    }


def friedman_test(columns: list[np.ndarray]) -> dict[str, Any]:
    """Критерий Фридмана для нескольких связанных выборок."""
    if len(columns) < 3:
        return {"applicable": False, "reason": "нужно минимум три связанные переменные"}
    if any(column.size < 2 for column in columns):
        return {"applicable": False, "reason": "слишком мало наблюдений"}
    sizes = {column.size for column in columns}
    if len(sizes) != 1:
        return {"applicable": False, "reason": "в связанных выборках должно быть одинаковое число наблюдений"}

    result = sps.friedmanchisquare(*columns)
    return {
        "applicable": True,
        "chi2": float(result.statistic),
        "df": float(len(columns) - 1),
        "p": float(result.pvalue),
        "n": int(columns[0].size),
    }


def _test_table(method: str, values: dict[str, Any]) -> Table:
    """Таблица с результатом основного критерия."""
    table = Table(title=f"Критерий: {METHOD_LABELS.get(method, method)}")

    if method == "mann_whitney":
        table.columns = [
            Column("", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ]
        table.add_row(["U Манна-Уитни", values["u"]])
        table.add_row(["W Уилкоксона", values["u"] + values["n1"] * (values["n1"] + 1) / 2])
        table.add_row(["Z (приближение)", _z_from_u(values)])
        table.add_row(["Асимпт. знач. (2-стор.)", values["p"]])
        table.add_row(["N группы 1", float(values["n1"])])
        table.add_row(["N группы 2", float(values["n2"])])
        table.footnote(
            "Размер эффекта: рангово-бисериальная корреляция "
            f"r = {values['rank_biserial']:.3f}."
        )
        if values.get("ties"):
            table.footnote("Есть связанные ранги; значимость дана с поправкой на связи.")
        return table

    if method == "kruskal_wallis":
        table.columns = [
            Column("", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ]
        table.add_row(["Хи-квадрат (H)", values["h"]])
        table.add_row(["ст. св.", values["df"]])
        table.add_row(["Асимпт. знач.", values["p"]])
        table.add_row(["N всего", float(values["n_total"])])
        table.footnote(
            "Размер эффекта: эпсилон-квадрат "
            f"= {values['epsilon_squared']:.3f}."
        )
        table.footnote(
            "Критерий сравнивает средние ранги групп, а не средние значения."
        )
        return table

    if method == "wilcoxon":
        table.columns = [
            Column("", align="left", is_metric=False),
            Column("Значение", decimals=3),
        ]
        table.add_row(["T Уилкоксона", values["t"]])
        table.add_row(["Асимпт. знач. (2-стор.)", values["p"]])
        table.add_row(["N пар", float(values["n"])])
        table.add_row(["Ненулевых разностей", float(values["nonzero"])])
        table.add_row(["Сумма положительных рангов", values["positive_sum"]])
        table.add_row(["Сумма отрицательных рангов", values["negative_sum"]])
        return table

    table.columns = [
        Column("", align="left", is_metric=False),
        Column("Значение", decimals=3),
    ]
    table.add_row(["Хи-квадрат Фридмана", values["chi2"]])
    table.add_row(["ст. св.", values["df"]])
    table.add_row(["Асимпт. знач.", values["p"]])
    table.add_row(["N (число объектов)", float(values["n"])])
    return table


def _z_from_u(values: dict[str, Any]) -> float:
    """Z-приближение для критерия Манна-Уитни (как в SPSS)."""
    n1, n2 = values["n1"], values["n2"]
    if n1 == 0 or n2 == 0:
        return float("nan")
    mean_u = n1 * n2 / 2.0
    sigma_u = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    if sigma_u <= 0:
        return float("nan")
    return (values["u"] - mean_u) / sigma_u


def _pairwise_table(rows: list[dict[str, Any]], method: str) -> Table:
    label = "Бонферрони" if method == "bonferroni" else "Холм"
    table = Table(
        title=f"Парные сравнения ({label})",
        columns=[
            Column("Группа 1", align="left", is_metric=False),
            Column("Группа 2", align="left", is_metric=False),
            Column("U", decimals=3),
            Column("знач. (скорр.)", decimals=3),
        ],
    )
    for row in rows:
        table.add_row([row["group1"], row["group2"], row["u"], row["p"]])
    table.footnote(
        "Парные критерии Манна-Уитни с поправкой на множественные сравнения - "
        "применяются после значимого критерия Краскела-Уоллиса."
    )
    return table


def run(command: NonparametricCommand) -> Result:
    dataset = command.dataset
    if dataset is None:
        raise CommandError("Команда не связана с набором данных")

    result = Result(procedure=command.PROCEDURE, title=command.TITLE, syntax=command.syntax())
    method = command.method

    # ------------------------------------------------- независимые выборки
    if command.kind == "independent":
        factor_var = dataset.var(command.group_var)
        for name in command.test_vars:
            dependent_name = dataset.var(name).display_name
            from winnow.stats.anova import split_groups

            raw_groups = split_groups(dataset, name, command.group_var)
            groups = [RankGroup(label=group.label, values=group.values) for group in raw_groups]

            if len(groups) < 2:
                result.warn(
                    f"{dependent_name}: групп с данными меньше двух - критерий не применён"
                )
                continue

            _rank_groups(groups)
            if command.descriptives:
                result.add_table(_descriptives_table(dependent_name, groups))
            result.add_table(_ranks_table(dependent_name, groups))

            chosen = method
            if method == "auto":
                chosen = "kruskal_wallis" if len(groups) > 2 else "mann_whitney"

            if chosen == "mann_whitney" and len(groups) != 2:
                result.warn(
                    f"{dependent_name}: для критерия Манна-Уитни нужны ровно две группы, "
                    f"а их {len(groups)} - выполнен критерий Краскела-Уоллиса"
                )
                chosen = "kruskal_wallis"

            if chosen == "mann_whitney":
                values = mann_whitney(groups)
                if not values.get("applicable"):
                    result.warn(f"{dependent_name}: {values.get('reason')}")
                    continue
                result.add_table(_test_table("mann_whitney", values))
                result.add_findings(
                    interpretation.rank_difference(
                        outcome=dataset.var(name).label or name,
                        method_title="критерий Манна-Уитни",
                        p_value=float(values["p"]),
                        statistic_name="U",
                        statistic=float(values["u"]),
                        groups=[
                            (group.label, float(group.mean_rank), group.n)
                            for group in groups
                        ],
                        effect=values.get("rank_biserial"),
                    )
                )
            else:
                values = kruskal_wallis(groups)
                if not values.get("applicable"):
                    result.warn(f"{dependent_name}: {values.get('reason')}")
                    continue
                result.add_table(_test_table("kruskal_wallis", values))
                rows = pairwise_mann_whitney(groups, "bonferroni")
                if rows:
                    result.add_table(_pairwise_table(rows, "bonferroni"))
                result.add_findings(
                    interpretation.rank_difference(
                        outcome=dataset.var(name).label or name,
                        method_title="критерий Краскела-Уоллиса",
                        p_value=float(values["p"]),
                        statistic_name="H",
                        statistic=float(values["h"]),
                        groups=[
                            (group.label, float(group.mean_rank), group.n)
                            for group in groups
                        ],
                    )
                )

    # ---------------------------------------------------- связанные выборки
    else:
        if method in ("auto", "wilcoxon"):
            for first_name, second_name in zip(command.test_vars, command.pair_with):
                label = f"{first_name} - {second_name}"
                frame = dataset.analysis_frame([first_name, second_name])
                first_series = pd.to_numeric(frame[first_name], errors="coerce")
                second_series = pd.to_numeric(frame[second_name], errors="coerce")
                mask = first_series.notna() & second_series.notna()
                first = first_series[mask].to_numpy(dtype=float)
                second = second_series[mask].to_numpy(dtype=float)

                if first.size < 2:
                    result.warn(f"{label}: меньше двух полных пар - критерий не применён")
                    continue

                if command.descriptives:
                    table = Table(
                        title=f"Описательные статистики: {label}",
                        columns=[
                            Column("", align="left", is_metric=False),
                            Column("N", decimals=0),
                            Column("Среднее", decimals=3),
                            Column("Стд. отклонение", decimals=3),
                            Column("Медиана", decimals=3),
                        ],
                    )
                    for title, array in ((first_name, first), (second_name, second)):
                        table.add_row(
                            [
                                title,
                                int(array.size),
                                float(np.mean(array)),
                                float(np.std(array, ddof=1)),
                                float(np.median(array)),
                            ]
                        )
                    result.add_table(table)

                values = wilcoxon_test(first, second)
                if not values.get("applicable"):
                    result.warn(f"{label}: {values.get('reason')}")
                    continue
                table = _test_table("wilcoxon", values)
                table.title = f"Критерий: {METHOD_LABELS['wilcoxon']} ({label})"
                result.add_table(table)

        else:  # Фридман
            frame = dataset.analysis_frame(command.test_vars)
            numeric = {
                name: pd.to_numeric(frame[name], errors="coerce") for name in command.test_vars
            }
            complete = pd.concat(numeric, axis=1).dropna()
            if complete.shape[0] < 2:
                result.warn("Фридман: меньше двух полных наблюдений - критерий не применён")
            else:
                columns = [complete[name].to_numpy(dtype=float) for name in command.test_vars]
                values = friedman_test(columns)
                if not values.get("applicable"):
                    result.warn(f"Фридман: {values.get('reason')}")
                else:
                    result.add_table(_test_table("friedman", values))

    if result.is_empty:
        result.warn("Ни одной таблицы не построено")
    return result


__all__ = [
    "METHOD_LABELS",
    "RankGroup",
    "friedman_test",
    "kruskal_wallis",
    "mann_whitney",
    "pairwise_mann_whitney",
    "run",
    "wilcoxon_test",
]

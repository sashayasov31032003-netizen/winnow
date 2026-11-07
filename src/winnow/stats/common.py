"""Общие расчётные утилиты процедур.

Здесь собрано то, что иначе расползлось бы копипастой по процедурам: подсчёт
валидных/пропущенных, статистики по группам, форматирование процентов.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.core.formatting import fmt_int, num


def valid_values(series: pd.Series) -> np.ndarray:
    """Числовой ряд без пропущенных значений."""
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def counts(series: pd.Series) -> tuple[int, int]:
    """(валидных, пропущенных) для одной переменной."""
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    valid = int(np.isfinite(numeric).sum())
    return valid, int(len(series)) - valid


def percent_value(part: float, whole: float) -> float | None:
    """Процент как число.

    Именно число, а не строка: рендерер сам добавит знак "%", а Excel получит
    числовое значение. Иначе экспорт в Excel превращает проценты в текст.
    """
    if not whole:
        return None
    return 100.0 * part / whole


def percent(part: float, whole: float, decimals: int = 1) -> str:
    """Процент как текст. Нужен там, где число и знак "%" неразделимы."""
    value = percent_value(part, whole)
    return "." if value is None else num(value, decimals) + "%"


@dataclass
class GroupStats:
    """Основные выборочные характеристики - нужны почти в каждой процедуре."""

    n: int
    mean: float
    std: float
    sem: float

    @property
    def valid(self) -> bool:
        return self.n > 0 and math.isfinite(self.mean)


def group_stats(values: np.ndarray) -> GroupStats:
    n = int(values.size)
    if n == 0:
        return GroupStats(0, float("nan"), float("nan"), float("nan"))
    mean = float(np.mean(values))
    if n < 2:
        return GroupStats(n, mean, float("nan"), float("nan"))
    std = float(np.std(values, ddof=1))
    return GroupStats(n, mean, std, std / math.sqrt(n))


def ordered_categories(
    series: pd.Series, value_labels: dict[Any, str] | None = None
) -> list[Any]:
    """Упорядоченный список категорий: числа по возрастанию, строки по алфавиту.

    Метки значений из паспорта добавляются, даже если в данных таких значений
    нет: иначе пользователь не увидит пустую категорию, которую сам же и описал.
    """
    observed = list(pd.unique(series.dropna()))
    if value_labels:
        for key in value_labels:
            if key not in observed:
                observed.append(key)

    if not observed:
        return []

    numeric = [v for v in observed if isinstance(v, (int, float, np.integer, np.floating))]
    if len(numeric) == len(observed):
        return sorted(observed, key=float)
    return sorted(observed, key=lambda v: str(v))


def category_label(value: Any, value_labels: dict[Any, str] | None) -> str:
    """Подпись категории в виде "код (метка)" или просто метка.

    Коды из файлов часто приходят как 2.0, хотя в паспорте записано 2. Поэтому
    перед сравнением значение приводится к целому: иначе в отчёте появится
    "2.0 (Нет)" вместо "2 (Нет)".
    """
    key = value
    if isinstance(value, (int, float)) and float(value).is_integer():
        key = int(value)

    if value_labels:
        for candidate in (value, key, float(value) if isinstance(value, (int, float)) else value):
            if candidate in value_labels:
                label = value_labels[candidate]
                return label if str(label) == str(key) else f"{format_code(key)} ({label})"
    return format_code(key)


def format_code(value: Any) -> str:
    """Код без лишней дробной части: 2.0 -> "2", 2.5 -> "2.5"."""
    if isinstance(value, float) and value.is_integer():
        return fmt_int(value)
    return str(value)


def numeric_frame(dataset: Dataset, names: list[str]) -> pd.DataFrame:
    """Числовые колонки, приведённые к float, с учётом пропусков набора."""
    frame = dataset.analysis_frame(names)
    return pd.DataFrame({name: pd.to_numeric(frame[name], errors="coerce") for name in names})


def t_ci(mean: float, std: float, n: int, confidence: float) -> tuple[float, float]:
    """Двусторонний доверительный интервал для среднего по t-распределению."""
    if n < 2 or not math.isfinite(std):
        return float("nan"), float("nan")
    sem = std / math.sqrt(n)
    critical = float(sps.t.ppf(1.0 - (1.0 - confidence) / 2.0, df=n - 1))
    margin = critical * sem
    return mean - margin, mean + margin


def p_from_t(t_value: float, df: float) -> float:
    """Двусторонняя значимость по значению t."""
    if not math.isfinite(t_value) or df <= 0:
        return float("nan")
    return float(2.0 * sps.t.sf(abs(t_value), df))


def cohens_d_pooled(m1: float, s1: float, n1: int, m2: float, s2: float, n2: int) -> float:
    """d Коэна с объединённым стандартным отклонением (как в SPSS/G*Power)."""
    if n1 < 2 or n2 < 2:
        return float("nan")
    pooled_var = ((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2)
    if pooled_var <= 0:
        return float("nan")
    return (m1 - m2) / math.sqrt(pooled_var)


def hedges_g(d: float, n1: int, n2: int) -> float:
    """Поправка Хеджеса на малую выборку."""
    if not math.isfinite(d):
        return float("nan")
    df = n1 + n2 - 2
    if df <= 1:
        return float("nan")
    correction = 1.0 - 3.0 / (4.0 * df - 1.0)
    return d * correction


# ---------------------------------------------------------------------------
# Сравнение нескольких групп: размеры эффекта, апостериорные сравнения, поправки
# ---------------------------------------------------------------------------


def eta_squared(ss_between: float, ss_total: float) -> float:
    """Доля объяснённой дисперсии для ANOVA.

    Самый ожидаемый размер эффекта: какую часть общего разброса объясняет
    группировка.
    """
    if not math.isfinite(ss_total) or ss_total <= 0:
        return float("nan")
    return ss_between / ss_total


def omega_squared(ss_between: float, ss_within: float, ms_within: float) -> float:
    """Омега-квадрат: менее смещённая оценка размера эффекта, чем эта-квадрат."""
    if not math.isfinite(ms_within) or ms_within <= 0:
        return float("nan")
    denominator = ss_within + ss_between + ms_within
    if denominator <= 0:
        return float("nan")
    return (ss_between - ms_within) / denominator


def epsilon_squared(h_statistic: float, n_total: int, k_groups: int) -> float:
    """Размер эффекта для критерия Краскела-Уоллиса."""
    if n_total - k_groups <= 0 or not math.isfinite(h_statistic):
        return float("nan")
    return h_statistic / (n_total - k_groups)


def rank_biserial_from_u(u_statistic: float, n1: int, n2: int) -> float:
    """Рангово-бисериальная корреляция для критерия Манна-Уитни."""
    if n1 <= 0 or n2 <= 0:
        return float("nan")
    return 1.0 - (2.0 * u_statistic) / (n1 * n2)


def bonferroni_adjust(p_values: list[float]) -> list[float]:
    """Поправка Бонферрони: p умножается на число сравнений, но не выше единицы."""
    count = len(p_values)
    if count == 0:
        return []
    return [min(1.0, p * count) if math.isfinite(p) else p for p in p_values]


def holm_adjust(p_values: list[float]) -> list[float]:
    """Поправка Холма - ступенчатая и менее консервативная, чем Бонферрони.

    Возвращает значения в исходном порядке: поправка накапливается по возрастанию p.
    """
    count = len(p_values)
    if count == 0:
        return []
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted: list[float] = [float("nan")] * count
    running = 0.0
    for rank, index in enumerate(order):
        value = p_values[index]
        if not math.isfinite(value):
            adjusted[index] = value
            continue
        running = max(running, value * (count - rank))
        adjusted[index] = min(1.0, running)
    return adjusted


def tukey_p_value(q_value: float, k_groups: int, df_within: float) -> float:
    """Значимость для критерия Тьюки через распределение стьюдентизированного размаха.

    scipy даёт именно это распределение, поэтому дополнительная зависимость не
    нужна и числа не расходятся с эталоном.
    """
    if not math.isfinite(q_value) or q_value <= 0:
        return float("nan")
    if k_groups < 2 or df_within <= 0:
        return float("nan")
    return float(sps.studentized_range.sf(q_value, k_groups, df_within))


def tukey_critical_q(confidence: float, k_groups: int, df_within: float) -> float:
    """Критическое значение q для доверительных интервалов Тьюки."""
    if k_groups < 2 or df_within <= 0:
        return float("nan")
    return float(sps.studentized_range.ppf(confidence, k_groups, df_within))


__all__ = [
    "GroupStats",
    "bonferroni_adjust",
    "category_label",
    "cohens_d_pooled",
    "counts",
    "epsilon_squared",
    "eta_squared",
    "group_stats",
    "hedges_g",
    "holm_adjust",
    "num",
    "numeric_frame",
    "omega_squared",
    "ordered_categories",
    "p_from_t",
    "percent",
    "percent_value",
    "rank_biserial_from_u",
    "t_ci",
    "tukey_critical_q",
    "tukey_p_value",
    "valid_values",
]

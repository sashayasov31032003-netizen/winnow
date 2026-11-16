"""Сравнение волн исследования: база и текущий срез.

Сравниваются только общие переменные двух наборов. Для количественных —
среднее/медиана и Welch t-test, для категориальных — распределения и χ².
Это независимые выборки, а не панель одних и тех же людей; отчёт говорит
об изменениях на уровне совокупности, а не о причинном эффекте.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.dataset import Dataset


@dataclass(frozen=True)
class MonitoringConfig:
    variables: tuple[str, ...] | None = None
    alpha: float = 0.05

    def as_payload(self) -> dict[str, Any]:
        return {
            "variables": list(self.variables) if self.variables is not None else None,
            "alpha": self.alpha,
        }


@dataclass
class MonitoringReport:
    baseline_name: str
    current_name: str
    baseline_n: int
    current_n: int
    variables: list[dict[str, Any]]
    summary: dict[str, Any]
    methodology: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "baseline": {"name": self.baseline_name, "n_cases": self.baseline_n},
            "current": {"name": self.current_name, "n_cases": self.current_n},
            "variables": _safe(self.variables),
            "summary": _safe(self.summary),
            "methodology": _safe(self.methodology),
        }


def compare_waves(
    baseline: Dataset,
    current: Dataset,
    config: MonitoringConfig | None = None,
) -> MonitoringReport:
    """Сравнивает две волны по общим переменным."""
    config = config or MonitoringConfig()
    alpha = min(0.2, max(0.001, float(config.alpha)))
    common = [name for name in baseline.names() if name in set(current.names())]
    if config.variables is not None:
        wanted = [name for name in config.variables if name in set(common)]
        common = wanted
    if not common:
        raise ValueError("У наборов нет общих переменных для сравнения")

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for name in common:
        base_var = baseline.var(name)
        cur_var = current.var(name)
        base_measure = _measure_key(base_var.measure)
        cur_measure = _measure_key(cur_var.measure)
        base_numeric = base_measure in {"scale", "ordinal"}
        cur_numeric = cur_measure in {"scale", "ordinal"}
        if base_numeric != cur_numeric:
            skipped.append(f"{name}: разный тип переменной")
            continue
        base_series = baseline.analysis_frame([name])[name]
        cur_series = current.analysis_frame([name])[name]
        if base_numeric:
            row = _numeric_row(
                name, base_var.display_name, base_measure, base_series, cur_series, alpha
            )
        else:
            row = _categorical_row(
                name, base_var.display_name, base_measure, base_series, cur_series, alpha
            )
        if row is None:
            skipped.append(f"{name}: недостаточно наблюдений или нет вариации")
            continue
        rows.append(row)

    if not rows:
        raise ValueError("Не удалось сравнить ни одной переменной: слишком мало данных")
    _apply_fdr(rows)
    for row in rows:
        row["significant"] = bool(row.get("q") is not None and row["q"] < alpha)

    numeric = [row for row in rows if row["kind"] == "numeric"]
    categorical = [row for row in rows if row["kind"] == "categorical"]
    changed = [row for row in rows if row["significant"]]
    summary = {
        "common_variables": len(common),
        "compared_variables": len(rows),
        "numeric": len(numeric),
        "categorical": len(categorical),
        "changed": len(changed),
        "stable": len(rows) - len(changed),
        "skipped": skipped,
        "top_changes": [
            {
                "name": row["name"],
                "display": row["display"],
                "kind": row["kind"],
                "change": row["change"].get("summary", ""),
                "p": row.get("p"),
                "q": row.get("q"),
            }
            for row in sorted(
                changed,
                key=lambda item: item.get("q", 1.0),
            )[:5]
        ],
    }
    methodology = {
        "design": "independent waves",
        "numeric": "среднее, медиана, Welch t-test, Cohen's d и 95 % ДИ разности",
        "categorical": "доли, χ² однородности, V Крамера",
        "multiple_testing": "Benjamini-Hochberg FDR",
        "missing": "pairwise",
        "alpha": alpha,
        "notes": [
            "Это независимые выборки: изменение среднего не доказывает эффект.",
            "Сравнивайте только сопоставимые вопросы и шкалы.",
            "Для порядковых переменных среднее — ориентир; смотрите медиану и доли.",
        ],
    }
    return MonitoringReport(
        baseline_name=baseline.name,
        current_name=current.name,
        baseline_n=baseline.n_cases,
        current_n=current.n_cases,
        variables=rows,
        summary=summary,
        methodology=methodology,
    )


def _numeric_row(
    name: str,
    display: str,
    measure: str,
    baseline: pd.Series,
    current: pd.Series,
    alpha: float,
) -> dict[str, Any] | None:
    base_values = pd.to_numeric(baseline, errors="coerce").dropna().to_numpy(dtype=float)
    cur_values = pd.to_numeric(current, errors="coerce").dropna().to_numpy(dtype=float)
    n1, n2 = len(base_values), len(cur_values)
    if n1 < 2 or n2 < 2:
        return None
    mean1, mean2 = float(np.mean(base_values)), float(np.mean(cur_values))
    var1, var2 = float(np.var(base_values, ddof=1)), float(np.var(cur_values, ddof=1))
    diff = mean2 - mean1
    percent = (diff / abs(mean1) * 100.0) if abs(mean1) > 1e-12 else None
    se = math.sqrt(var1 / n1 + var2 / n2)
    if se <= 0:
        ci_low = ci_high = diff
        p_value = 1.0 if abs(diff) < 1e-12 else 0.0
    else:
        df = (var1 / n1 + var2 / n2) ** 2 / (
            (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        )
        critical = float(sps.t.ppf(1.0 - alpha / 2.0, df))
        ci_low, ci_high = diff - critical * se, diff + critical * se
        p_value = float(sps.ttest_ind(base_values, cur_values, equal_var=False).pvalue)
    pooled = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    cohen_d = diff / pooled if pooled > 0 else None
    warning = ""
    if measure == "ordinal":
        warning = "порядковая переменная: среднее — ориентир"
    elif min(n1, n2) < 30:
        warning = "мало наблюдений"
    direction = "up" if diff > 0 else "down" if diff < 0 else "same"
    return {
        "name": name,
        "display": display,
        "kind": "numeric",
        "measure": measure,
        "baseline": {
            "n": n1,
            "missing": int(baseline.isna().sum()),
            "mean": _round(mean1),
            "sd": _round(math.sqrt(var1)),
            "median": _round(float(np.median(base_values))),
        },
        "current": {
            "n": n2,
            "missing": int(current.isna().sum()),
            "mean": _round(mean2),
            "sd": _round(math.sqrt(var2)),
            "median": _round(float(np.median(cur_values))),
        },
        "change": {
            "mean_diff": _round(diff),
            "percent": _round(percent),
            "ci_low": _round(ci_low),
            "ci_high": _round(ci_high),
            "cohen_d": _round(cohen_d),
            "direction": direction,
            "summary": (
                f"{diff:+.2f}"
                + (f" ({percent:+.1f} %)" if percent is not None else "")
                + f", p = {p_value:.3f}"
            ),
        },
        "p": _finite(p_value),
        "q": None,
        "significant": False,
        "warning": warning,
    }


def _categorical_row(
    name: str,
    display: str,
    measure: str,
    baseline: pd.Series,
    current: pd.Series,
    alpha: float,
) -> dict[str, Any] | None:
    base = baseline.dropna().astype(str)
    cur = current.dropna().astype(str)
    n1, n2 = len(base), len(cur)
    if n1 < 2 or n2 < 2:
        return None
    categories = sorted(set(base.unique()) | set(cur.unique()))
    if len(categories) < 2:
        return None
    base_counts = {category: int((base == category).sum()) for category in categories}
    cur_counts = {category: int((cur == category).sum()) for category in categories}
    table = np.array(
        [[base_counts[category] for category in categories], [cur_counts[category] for category in categories]],
        dtype=float,
    )
    try:
        chi2, p_value, dof, expected = sps.chi2_contingency(table, correction=False)
    except ValueError:
        return None
    denominator = min(1, len(categories) - 1)
    cramers = math.sqrt(max(0.0, float(chi2) / (n1 + n2) * denominator)) if denominator else None
    base_shares = {key: base_counts[key] / n1 for key in categories}
    cur_shares = {key: cur_counts[key] / n2 for key in categories}
    points = {key: (cur_shares[key] - base_shares[key]) * 100.0 for key in categories}
    warning = ""
    if float(expected.min()) < 5:
        warning = "ожидаемые частоты < 5"
    if min(n1, n2) < 30:
        warning = (warning + "; " if warning else "") + "мало наблюдений"
    return {
        "name": name,
        "display": display,
        "kind": "categorical",
        "measure": measure,
        "baseline": {
            "n": n1,
            "missing": int(baseline.isna().sum()),
            "counts": base_counts,
            "shares": {key: _round(value) for key, value in base_shares.items()},
        },
        "current": {
            "n": n2,
            "missing": int(current.isna().sum()),
            "counts": cur_counts,
            "shares": {key: _round(value) for key, value in cur_shares.items()},
        },
        "change": {
            "chi2": _round(float(chi2)),
            "df": int(dof),
            "cramers_v": _round(cramers),
            "share_points": {key: _round(value) for key, value in points.items()},
            "summary": f"χ² = {chi2:.2f}, p = {p_value:.3f}",
        },
        "p": _finite(float(p_value)),
        "q": None,
        "significant": False,
        "warning": warning,
    }


def _apply_fdr(rows: list[dict[str, Any]]) -> None:
    valid = [row for row in rows if row.get("p") is not None]
    ordered = sorted(valid, key=lambda row: row["p"])
    count = len(ordered)
    previous = 1.0
    for rank in range(count - 1, -1, -1):
        row = ordered[rank]
        q_value = min(previous, row["p"] * count / (rank + 1))
        row["q"] = min(1.0, max(0.0, q_value))
        previous = row["q"]


def _measure_key(measure: Any) -> str:
    value = getattr(measure, "value", str(measure))
    return str(value).lower()


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 4) if math.isfinite(number) else None


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _finite(float(value))
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_safe(item) for item in value.tolist()]
    return value


__all__ = ["MonitoringConfig", "MonitoringReport", "compare_waves"]

"""Тренды по трём и более волнам исследования.

Тренд считается по средним (количественные) или долям (категориальные) с
поправкой на множественные сравнения. Это описание динамики, а не причинный
эффект; волны — независимые выборки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.dataset import Dataset


@dataclass(frozen=True)
class TrendWave:
    label: str
    dataset: Dataset
    year: int | None = None
    dataset_id: int | None = None
    position: int = 0


@dataclass
class TrendReport:
    waves: list[dict[str, Any]]
    variables: list[dict[str, Any]]
    summary: dict[str, Any]
    methodology: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "waves": _safe(self.waves),
            "variables": _safe(self.variables),
            "summary": _safe(self.summary),
            "methodology": _safe(self.methodology),
        }


def analyze_trends(
    waves: Iterable[TrendWave],
    variables: Iterable[str] | None = None,
    alpha: float = 0.05,
) -> TrendReport:
    """Считает тренды по общим переменным всех волн."""
    items = list(waves)
    if len(items) < 2:
        raise ValueError("Для тренда нужны минимум две волны")
    alpha = min(0.2, max(0.001, float(alpha)))
    common = [
        name
        for name in items[0].dataset.names()
        if all(name in set(wave.dataset.names()) for wave in items[1:])
    ]
    if variables is not None:
        wanted = [name for name in variables if name in set(common)]
        common = wanted
    if not common:
        raise ValueError("У волн нет общих переменных для тренда")

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for name in common:
        measures = [_measure_key(w.dataset.var(name).measure) for w in items]
        numeric = [m in {"scale", "ordinal"} for m in measures]
        if all(numeric):
            row = _numeric_trend(name, items, measures[0])
        elif not any(numeric):
            row = _categorical_trend(name, items, measures[0])
        else:
            skipped.append(f"{name}: тип переменной различается между волнами")
            continue
        if row is None:
            skipped.append(f"{name}: недостаточно наблюдений")
            continue
        row["display"] = items[0].dataset.var(name).display_name
        rows.append(row)

    if not rows:
        raise ValueError("Не удалось построить тренды: слишком мало данных")
    _apply_fdr(rows)
    for row in rows:
        row["significant"] = bool(row.get("q") is not None and row["q"] < alpha)

    changed = [row for row in rows if row["significant"]]
    summary = {
        "n_waves": len(items),
        "common_variables": len(common),
        "compared_variables": len(rows),
        "changed": len(changed),
        "stable": len(rows) - len(changed),
        "skipped": skipped,
        "top_trends": [
            {
                "name": row["name"],
                "display": row["display"],
                "kind": row["kind"],
                "summary": row["trend"]["summary"],
                "q": row.get("q"),
            }
            for row in sorted(changed, key=lambda item: item.get("q", 1.0))[:5]
        ],
    }
    methodology = {
        "design": "independent waves",
        "numeric": "средние по волнам, линейный тренд (OLS), p и FDR",
        "categorical": "доли по волнам, χ² однородности и V Крамера",
        "multiple_testing": "Benjamini-Hochberg FDR",
        "alpha": alpha,
        "notes": [
            "Тренд описывает динамику показателя, но не доказывает причину.",
            "Волны — независимые выборки, а не одни и те же респонденты.",
            "Сравнивайте одинаковые вопросы и шкалы.",
        ],
    }
    return TrendReport(
        waves=[
            {
                "id": item.dataset_id,
                "label": item.label,
                "year": item.year,
                "n_cases": item.dataset.n_cases,
                "position": item.position,
            }
            for item in items
        ],
        variables=rows,
        summary=summary,
        methodology=methodology,
    )


def _numeric_trend(name: str, waves: list[TrendWave], measure: str) -> dict[str, Any] | None:
    values: list[np.ndarray] = []
    for wave in waves:
        series = pd.to_numeric(wave.dataset.analysis_frame([name])[name], errors="coerce").dropna()
        values.append(series.to_numpy(dtype=float))
    if any(len(value) < 2 for value in values):
        return None
    means = [float(np.mean(value)) for value in values]
    medians = [float(np.median(value)) for value in values]
    years = [wave.year for wave in waves]
    if all(year is not None for year in years):
        x = np.asarray([int(year) for year in years], dtype=float)
        x_label = "год"
    else:
        x = np.arange(len(waves), dtype=float)
        x_label = "номер волны"
    if len(set(x.tolist())) < 2:
        return None
    regression = sps.linregress(x, np.asarray(means, dtype=float))
    slope = float(regression.slope)
    p_value = float(regression.pvalue) if len(waves) >= 3 else None
    change = means[-1] - means[0]
    percent = (change / abs(means[0]) * 100.0) if abs(means[0]) > 1e-12 else None
    direction = "up" if slope > 0 else "down" if slope < 0 else "same"
    return {
        "name": name,
        "kind": "numeric",
        "measure": measure,
        "waves": [
            {
                "label": wave.label,
                "year": wave.year,
                "n": len(value),
                "mean": _round(mean),
                "median": _round(median),
                "sd": _round(float(np.std(value, ddof=1))),
            }
            for wave, value, mean, median in zip(waves, values, means, medians)
        ],
        "trend": {
            "slope": _round(slope),
            "slope_unit": x_label,
            "r_squared": _round(float(regression.rvalue**2)),
            "p": _finite(p_value),
            "change": _round(change),
            "percent": _round(percent),
            "direction": direction,
            "summary": (
                f"{slope:+.2f} за {x_label}"
                + (f", изменение {change:+.2f}" if change else "")
                + (f" ({percent:+.1f} %)" if percent is not None else "")
            ),
        },
        "p": _finite(p_value),
        "q": None,
        "significant": False,
        "warning": "порядковая переменная: среднее — ориентир" if measure == "ordinal" else "",
    }


def _categorical_trend(name: str, waves: list[TrendWave], measure: str) -> dict[str, Any] | None:
    series: list[pd.Series] = []
    for wave in waves:
        values = wave.dataset.analysis_frame([name])[name].dropna().astype(str)
        if len(values) < 2:
            return None
        series.append(values)
    categories = sorted(set().union(*(set(values.unique()) for values in series)))
    if len(categories) < 2:
        return None
    counts = np.array(
        [[int((values == category).sum()) for category in categories] for values in series],
        dtype=float,
    )
    try:
        chi2, p_value, dof, expected = sps.chi2_contingency(counts, correction=False)
    except ValueError:
        return None
    total = float(counts.sum())
    denominator = min(len(waves) - 1, len(categories) - 1)
    cramers = math.sqrt(chi2 / (total * denominator)) if denominator else None
    shares = counts / counts.sum(axis=1, keepdims=True)
    shifts = {
        category: (shares[-1, index] - shares[0, index]) * 100.0
        for index, category in enumerate(categories)
    }
    max_shift = max(shifts.values(), key=abs) if shifts else 0.0
    warning = "ожидаемые частоты < 5" if float(expected.min()) < 5 else ""
    return {
        "name": name,
        "kind": "categorical",
        "measure": measure,
        "waves": [
            {
                "label": wave.label,
                "year": wave.year,
                "n": int(counts[index].sum()),
                "counts": {category: int(counts[index, position]) for position, category in enumerate(categories)},
                "shares": {
                    category: _round(float(shares[index, position]))
                    for position, category in enumerate(categories)
                },
            }
            for index, wave in enumerate(waves)
        ],
        "trend": {
            "chi2": _round(float(chi2)),
            "df": int(dof),
            "cramers_v": _round(cramers),
            "share_points": {category: _round(value) for category, value in shifts.items()},
            "max_shift": _round(max_shift),
            "summary": f"макс. сдвиг {max_shift:+.1f} п.п.; χ² = {chi2:.2f}",
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


__all__ = ["TrendReport", "TrendWave", "analyze_trends"]

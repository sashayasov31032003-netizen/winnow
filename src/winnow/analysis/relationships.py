"""Карта взаимосвязей переменных: корреляции и меры связи.

Карта показывает статистические связи, а не причинность. Для количественных пар
считаются Pearson / Spearman / Kendall (по выбору), для категориальных —
V Крамера, для количественно-категориальных — η² (корреляционное отношение).
Пропуски исключаются попарно.

Модуль не знает про HTTP и не меняет данные.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats as sps

from winnow.core.dataset import Dataset
from winnow.core.variable import Measure

METHODS = ("auto", "pearson", "spearman", "kendall")
NUMERIC_METHODS = ("pearson", "spearman", "kendall")
METHOD_LABELS = {
    "auto": "авто",
    "pearson": "Пирсон (r)",
    "spearman": "Спирмен (ρ)",
    "kendall": "Кендалл (τ-b)",
    "cramers_v": "V Крамера",
    "eta_squared": "η²",
}
GROUP_LABELS = {
    "scale": "Количественные",
    "ordinal": "Порядковые",
    "nominal": "Категориальные",
    "other": "Другие",
}
GROUP_ORDER = ("scale", "ordinal", "nominal", "other")
DEFAULT_MAX_VARIABLES = 60
MIN_PAIR_N = 5


@dataclass(frozen=True)
class RelationshipConfig:
    method: str = "auto"
    max_variables: int = DEFAULT_MAX_VARIABLES

    def as_payload(self) -> dict[str, Any]:
        return {"method": self.method, "max_variables": self.max_variables}


@dataclass
class RelationshipNode:
    name: str
    label: str
    display: str
    type: str
    measure: str
    group: str
    n: int
    n_missing: int
    n_unique: int
    available: bool
    reason: str = ""
    degree: int = 0
    significant_degree: int = 0
    recommendations: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": self.name,
            "label": self.label,
            "display": self.display,
            "type": self.type,
            "measure": self.measure,
            "group": self.group,
            "group_label": GROUP_LABELS.get(self.group, self.group),
            "n": self.n,
            "n_missing": self.n_missing,
            "n_unique": self.n_unique,
            "available": self.available,
            "reason": self.reason,
            "degree": self.degree,
            "significant_degree": self.significant_degree,
            "recommendations": list(self.recommendations),
        }


@dataclass
class RelationshipEdge:
    source: str
    target: str
    method: str
    kind: str
    statistic: float
    strength: float
    p_value: float
    q_value: float | None
    n: int
    direction: str
    significant: bool
    warning: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}__{self.target}"

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "method": self.method,
            "method_label": METHOD_LABELS.get(self.method, self.method),
            "kind": self.kind,
            "statistic": _round(self.statistic),
            "strength": _round(self.strength),
            "p": _finite(self.p_value),
            "q": _finite(self.q_value),
            "n": self.n,
            "direction": self.direction,
            "significant": self.significant,
            "warning": self.warning,
            **self.extra,
        }


@dataclass
class RelationshipMap:
    nodes: list[RelationshipNode]
    edges: list[RelationshipEdge]
    summary: dict[str, Any]
    methodology: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "nodes": [node.as_payload() for node in self.nodes],
            "edges": [edge.as_payload() for edge in self.edges],
            "summary": _safe(self.summary),
            "methodology": _safe(self.methodology),
        }


def build_relationship_map(
    dataset: Dataset, config: RelationshipConfig | None = None
) -> RelationshipMap:
    """Считает узлы и связи. Исходные данные не изменяются."""
    config = config or RelationshipConfig()
    method = config.method if config.method in METHODS else "auto"
    names = list(dataset.names())
    truncated = len(names) > max(1, int(config.max_variables))
    shown = names[: max(1, int(config.max_variables))]
    frame = dataset.analysis_frame(shown)

    nodes: list[RelationshipNode] = []
    series: dict[str, pd.Series] = {}
    for name in shown:
        variable = dataset.var(name)
        raw = frame[name]
        series[name] = raw
        n = int(raw.notna().sum())
        n_unique = int(raw.nunique(dropna=True))
        measure = _measure_key(variable.measure)
        group = measure if measure in GROUP_LABELS else "other"
        available = True
        reason = ""
        if n == 0:
            available, reason = False, "нет наблюдений"
        elif n_unique <= 1:
            available, reason = False, "переменная не меняется"
        elif variable.var_type.value == "date":
            available, reason = False, "дата не сравнивается как связь"
        elif measure == "nominal" and n_unique > max(20, int(n * 0.5)):
            available, reason = False, "слишком много уникальных категорий"
        nodes.append(
            RelationshipNode(
                name=name,
                label=variable.label or name,
                display=variable.display_name,
                type=variable.var_type.value,
                measure=measure,
                group=group,
                n=n,
                n_missing=int(raw.isna().sum()),
                n_unique=n_unique,
                available=available,
                reason=reason,
            )
        )

    by_name = {node.name: node for node in nodes}
    edges: list[RelationshipEdge] = []
    for first_index, first in enumerate(shown):
        for second in shown[first_index + 1 :]:
            node_a, node_b = by_name[first], by_name[second]
            if not node_a.available or not node_b.available:
                continue
            edge = _pair_edge(
                series[first],
                series[second],
                first,
                second,
                node_a.measure,
                node_b.measure,
                method,
            )
            if edge is not None:
                edges.append(edge)

    _apply_fdr(edges)
    edges.sort(key=lambda edge: (edge.strength, -edge.p_value), reverse=True)
    for edge in edges:
        edge.significant = bool(edge.q_value is not None and edge.q_value < 0.05)
        by_name[edge.source].degree += 1
        by_name[edge.target].degree += 1
        if edge.significant:
            by_name[edge.source].significant_degree += 1
            by_name[edge.target].significant_degree += 1

    _node_recommendations(nodes, edges)
    summary = _summary(nodes, edges, config, truncated, len(names))
    methodology = {
        "method": method,
        "method_label": METHOD_LABELS[method],
        "missing": "pairwise",
        "min_n": MIN_PAIR_N,
        "multiple_testing": "Benjamini-Hochberg FDR",
        "strength": "|r| для корреляций, V Крамера, η² для смешанных пар",
        "groups": {key: GROUP_LABELS[key] for key in GROUP_ORDER},
        "notes": [
            "Связь не означает причинность.",
            "Пропуски исключены попарно, поэтому N зависит от пары.",
            "Сильные корреляции — повод проверить мультиколлинеарность, а не готовый вывод.",
            "V Крамера и η² не имеют направления; для них линия нейтральная.",
        ],
    }
    return RelationshipMap(
        nodes=nodes,
        edges=edges,
        summary=summary,
        methodology=methodology,
    )


def _pair_edge(
    first: pd.Series,
    second: pd.Series,
    first_name: str,
    second_name: str,
    first_measure: str,
    second_measure: str,
    method: str,
) -> RelationshipEdge | None:
    numeric_first = first_measure in {"scale", "ordinal"}
    numeric_second = second_measure in {"scale", "ordinal"}

    if numeric_first and numeric_second:
        selection = method if method in NUMERIC_METHODS else _auto_numeric(first_measure, second_measure)
        a = pd.to_numeric(first, errors="coerce")
        b = pd.to_numeric(second, errors="coerce")
        mask = a.notna() & b.notna()
        a = a[mask].to_numpy(dtype=float)
        b = b[mask].to_numpy(dtype=float)
        n = int(len(a))
        if n < MIN_PAIR_N or np.std(a, ddof=1) == 0 or np.std(b, ddof=1) == 0:
            return None
        if selection == "pearson":
            statistic, p_value = sps.pearsonr(a, b)
        elif selection == "spearman":
            statistic, p_value = sps.spearmanr(a, b)
        else:
            statistic, p_value = sps.kendalltau(a, b, variant="b")
        if not math.isfinite(float(statistic)) or not math.isfinite(float(p_value)):
            return None
        strength = min(1.0, abs(float(statistic)))
        direction = "positive" if statistic > 0 else "negative" if statistic < 0 else "none"
        warning = "мало наблюдений" if n < 30 else ""
        return RelationshipEdge(
            source=first_name,
            target=second_name,
            method=selection,
            kind="numeric",
            statistic=float(statistic),
            strength=strength,
            p_value=float(p_value),
            q_value=None,
            n=n,
            direction=direction,
            significant=False,
            warning=warning,
        )

    if not numeric_first and not numeric_second:
        mask = first.notna() & second.notna()
        a = first[mask]
        b = second[mask]
        n = int(len(a))
        if n < MIN_PAIR_N:
            return None
        table = pd.crosstab(a.astype(str), b.astype(str))
        if table.shape[0] < 2 or table.shape[1] < 2:
            return None
        try:
            chi2, p_value, _dof, expected = sps.chi2_contingency(
                table, correction=False
            )
        except ValueError:
            return None
        denominator = n * min(table.shape[0] - 1, table.shape[1] - 1)
        if denominator <= 0:
            return None
        cramers = math.sqrt(max(0.0, float(chi2) / denominator))
        warning = ""
        if float(expected.min()) < 5:
            warning = "ожидаемые частоты < 5"
        if n < 30:
            warning = (warning + "; " if warning else "") + "мало наблюдений"
        return RelationshipEdge(
            source=first_name,
            target=second_name,
            method="cramers_v",
            kind="categorical",
            statistic=float(cramers),
            strength=min(1.0, cramers),
            p_value=float(p_value),
            q_value=None,
            n=n,
            direction="none",
            significant=False,
            warning=warning,
            extra={"rows": int(table.shape[0]), "columns": int(table.shape[1])},
        )

    # Смешанная пара: количественная + категориальная. η² показывает долю
    # дисперсии, объяснённую группами; направление не определено.
    if numeric_first:
        value_series = pd.to_numeric(first, errors="coerce")
        group_series = second
    else:
        value_series = pd.to_numeric(second, errors="coerce")
        group_series = first
    mask = value_series.notna() & group_series.notna()
    values = value_series[mask].to_numpy(dtype=float)
    groups = group_series[mask].astype(str)
    if len(values) < MIN_PAIR_N:
        return None
    labels = list(pd.unique(groups))
    if len(labels) < 2 or len(labels) > 30:
        return None
    grouped = [values[(groups == label).to_numpy()] for label in labels]
    sizes = [len(group) for group in grouped]
    if any(size == 0 for size in sizes) or sum(sizes) <= len(labels):
        return None
    grand_mean = float(np.mean(values))
    ss_between = float(sum(size * (np.mean(group) - grand_mean) ** 2 for size, group in zip(sizes, grouped)))
    ss_within = float(sum(np.sum((group - np.mean(group)) ** 2) for group in grouped))
    ss_total = ss_between + ss_within
    if ss_total <= 0:
        return None
    eta_squared = max(0.0, min(1.0, ss_between / ss_total))
    df_between = len(labels) - 1
    df_within = len(values) - len(labels)
    if df_within <= 0:
        return None
    f_value = (ss_between / df_between) / (ss_within / df_within) if ss_within > 0 else float("inf")
    p_value = float(sps.f.sf(f_value, df_between, df_within))
    warning = "мало наблюдений" if len(values) < 30 else ""
    return RelationshipEdge(
        source=first_name,
        target=second_name,
        method="eta_squared",
        kind="mixed",
        statistic=eta_squared,
        strength=eta_squared,
        p_value=p_value,
        q_value=None,
        n=len(values),
        direction="none",
        significant=False,
        warning=warning,
        extra={"groups": len(labels), "eta_squared": _round(eta_squared)},
    )


def _auto_numeric(first_measure: str, second_measure: str) -> str:
    if first_measure == "scale" and second_measure == "scale":
        return "pearson"
    return "spearman"


def _apply_fdr(edges: list[RelationshipEdge]) -> None:
    valid = [edge for edge in edges if math.isfinite(edge.p_value)]
    if not valid:
        return
    ordered = sorted(valid, key=lambda edge: edge.p_value)
    count = len(ordered)
    previous = 1.0
    for rank in range(count - 1, -1, -1):
        edge = ordered[rank]
        q_value = min(previous, edge.p_value * count / (rank + 1))
        edge.q_value = min(1.0, max(0.0, q_value))
        previous = edge.q_value


def _node_recommendations(nodes: list[RelationshipNode], edges: list[RelationshipEdge]) -> None:
    by_name = {node.name: node for node in nodes}
    for node in nodes:
        if not node.available:
            node.recommendations.append(f"Переменная не включена в связи: {node.reason}.")
            continue
        strong = [
            edge
            for edge in edges
            if (edge.source == node.name or edge.target == node.name)
            and edge.significant
            and edge.strength >= 0.5
        ]
        if len(strong) >= 3:
            node.recommendations.append(
                "Много сильных связей: проверьте мультиколлинеарность, если переменная будет предиктором."
            )
        for edge in strong[:2]:
            other = edge.target if edge.source == node.name else edge.source
            node.recommendations.append(
                f"Связь с «{by_name[other].display}»: "
                f"{METHOD_LABELS.get(edge.method, edge.method)}, {edge.statistic:.2f}."
            )
        if node.n < 30:
            node.recommendations.append("Мало наблюдений: интерпретируйте связи осторожно.")
        if not strong:
            node.recommendations.append("Сильных статистически значимых связей не найдено.")


def _summary(
    nodes: list[RelationshipNode],
    edges: list[RelationshipEdge],
    config: RelationshipConfig,
    truncated: bool,
    total_variables: int,
) -> dict[str, Any]:
    valid_edges = [edge for edge in edges if edge.significant]
    strong = [edge for edge in edges if edge.strength >= 0.7 and edge.significant]
    numeric_strong = [
        edge
        for edge in strong
        if edge.kind == "numeric" and abs(edge.statistic) >= 0.8
    ]
    most_connected = sorted(
        (node for node in nodes if node.available),
        key=lambda node: (node.significant_degree, node.degree),
        reverse=True,
    )[:5]
    recommendations: list[str] = []
    for edge in numeric_strong[:3]:
        recommendations.append(
            f"«{edge.source}» и «{edge.target}»: |r| = {abs(edge.statistic):.2f}. "
            "Проверьте VIF, если обе переменные — предикторы."
        )
    if most_connected and most_connected[0].significant_degree:
        node = most_connected[0]
        recommendations.append(
            f"У «{node.display}» больше всего значимых связей "
            f"({node.significant_degree}); начните изучение с неё."
        )
    if not valid_edges:
        recommendations.append(
            "Статистически значимых связей не найдено; это не доказывает их отсутствие."
        )
    if truncated:
        recommendations.append(
            f"Показаны первые {config.max_variables} переменных из {total_variables}."
        )
    return {
        "n_nodes": len(nodes),
        "n_available": sum(node.available for node in nodes),
        "n_edges": len(edges),
        "n_significant": len(valid_edges),
        "n_strong": len(strong),
        "n_potential_collinearity": len(numeric_strong),
        "method": config.method,
        "strongest": [
            edge.as_payload() for edge in sorted(edges, key=lambda item: item.strength, reverse=True)[:8]
        ],
        "most_connected": [
            {
                "name": node.name,
                "display": node.display,
                "degree": node.degree,
                "significant_degree": node.significant_degree,
            }
            for node in most_connected
        ],
        "recommendations": recommendations[:8],
        "truncated": truncated,
        "total_variables": total_variables,
    }


def _measure_key(measure: Measure) -> str:
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
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _finite(float(value))
    if isinstance(value, np.ndarray):
        return [_safe(item) for item in value.tolist()]
    return value


__all__ = [
    "DEFAULT_MAX_VARIABLES",
    "GROUP_LABELS",
    "METHODS",
    "RelationshipConfig",
    "RelationshipEdge",
    "RelationshipMap",
    "RelationshipNode",
    "build_relationship_map",
]

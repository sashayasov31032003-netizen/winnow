"""Тесты карты взаимосвязей: корреляции, категориальные и смешанные пары."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from winnow.analysis.relationships import (
    RelationshipConfig,
    build_relationship_map,
)
from winnow.core.dataset import Dataset


def _dataset(n: int = 80) -> tuple[Dataset, pd.DataFrame]:
    rng = np.random.default_rng(2027)
    x = rng.normal(0, 1, n)
    y = 2.0 + 0.9 * x + rng.normal(0, 0.6, n)
    z = rng.normal(0, 1, n)
    group = np.where(np.arange(n) % 2 == 0, "a", "b")
    city = np.where(np.arange(n) % 3 == 0, "moscow", "other")
    constant = np.ones(n)
    frame = pd.DataFrame(
        {
            "x": x,
            "y": y,
            "z": z,
            "group": group,
            "city": city,
            "constant": constant,
            "identifier": [f"id-{index}" for index in range(n)],
        }
    )
    return Dataset.from_dataframe(frame, "relations"), frame


def _edge(result, source: str, target: str):
    return next(
        edge
        for edge in result.edges
        if {edge.source, edge.target} == {source, target}
    )


def test_pearson_and_node_groups():
    dataset, frame = _dataset()
    result = build_relationship_map(dataset, RelationshipConfig(method="pearson"))
    edge = _edge(result, "x", "y")
    expected_r, expected_p = sps.pearsonr(frame["x"], frame["y"])
    assert edge.method == "pearson"
    assert edge.statistic == pytest.approx(expected_r, abs=1e-10)
    assert edge.p_value == pytest.approx(expected_p, abs=1e-12)
    assert edge.direction == "positive"
    assert edge.significant is True

    by_name = {node.name: node for node in result.nodes}
    assert by_name["x"].group == "scale"
    assert by_name["group"].group == "nominal"
    assert by_name["constant"].available is False
    assert "идентификатор" not in by_name["group"].reason


def test_spearman_auto_for_ordinal_and_kendall_override():
    dataset, frame = _dataset()
    auto = build_relationship_map(dataset, RelationshipConfig(method="auto"))
    edge = _edge(auto, "x", "y")
    assert edge.method in {"pearson", "spearman"}

    kendall = build_relationship_map(dataset, RelationshipConfig(method="kendall"))
    edge = _edge(kendall, "x", "y")
    expected_tau, _ = sps.kendalltau(frame["x"], frame["y"], variant="b")
    assert edge.method == "kendall"
    assert edge.statistic == pytest.approx(expected_tau, abs=1e-10)


def test_categorical_and_mixed_edges_have_no_direction():
    dataset, _frame = _dataset()
    result = build_relationship_map(dataset, RelationshipConfig(method="pearson"))
    categorical = _edge(result, "group", "city")
    assert categorical.kind == "categorical"
    assert categorical.method == "cramers_v"
    assert categorical.direction == "none"
    mixed = _edge(result, "x", "group")
    assert mixed.kind == "mixed"
    assert mixed.method == "eta_squared"
    assert mixed.direction == "none"
    assert 0 <= mixed.strength <= 1


def test_map_does_not_modify_source_and_payload_is_serializable():
    dataset, frame = _dataset()
    before = frame.copy(deep=True)
    result = build_relationship_map(dataset)
    pd.testing.assert_frame_equal(frame, before)
    payload = result.as_payload()
    assert payload["nodes"] and payload["edges"]
    assert payload["summary"]["n_nodes"] == len(result.nodes)
    assert "recommendations" in payload["summary"]
    assert all("p" in edge for edge in payload["edges"])


def test_max_variables_truncates_and_reports_it():
    dataset, _frame = _dataset()
    result = build_relationship_map(dataset, RelationshipConfig(max_variables=3))
    assert len(result.nodes) == 3
    assert result.summary["truncated"] is True
    assert result.summary["total_variables"] == 7

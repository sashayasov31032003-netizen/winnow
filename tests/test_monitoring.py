"""Тесты сравнения волн исследования."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from winnow.analysis.monitoring import MonitoringConfig, compare_waves
from winnow.core.dataset import Dataset


def _datasets(n: int = 80):
    rng = np.random.default_rng(2028)
    base = pd.DataFrame(
        {
            "score": rng.normal(10, 2, n),
            "group": np.where(np.arange(n) % 2 == 0, "a", "b"),
            "age": rng.integers(18, 60, n),
        }
    )
    current = pd.DataFrame(
        {
            "score": rng.normal(11.5, 2.2, n),
            "group": np.where(np.arange(n) % 3 == 0, "a", "b"),
            "age": rng.integers(18, 60, n),
        }
    )
    return Dataset.from_dataframe(base, "2024"), Dataset.from_dataframe(current, "2025"), base, current


def test_numeric_and_categorical_waves_are_compared():
    base, current, _b, _c = _datasets()
    report = compare_waves(base, current)
    assert report.baseline_name == "2024"
    assert report.current_name == "2025"
    score = next(row for row in report.variables if row["name"] == "score")
    assert score["kind"] == "numeric"
    assert score["current"]["mean"] > score["baseline"]["mean"]
    assert score["change"]["mean_diff"] > 0
    assert score["p"] is not None and score["q"] is not None
    group = next(row for row in report.variables if row["name"] == "group")
    assert group["kind"] == "categorical"
    assert set(group["change"]["share_points"]) == {"a", "b"}
    assert report.summary["compared_variables"] == 3


def test_missing_common_variables_raise():
    a = Dataset.from_dataframe(pd.DataFrame({"x": [1, 2, 3]}), "a")
    b = Dataset.from_dataframe(pd.DataFrame({"y": [1, 2, 3]}), "b")
    with pytest.raises(ValueError, match="общих"):
        compare_waves(a, b)


def test_selected_variables_and_no_mutation():
    base, current, base_frame, current_frame = _datasets()
    before_base = base_frame.copy(deep=True)
    before_current = current_frame.copy(deep=True)
    report = compare_waves(
        base,
        current,
        MonitoringConfig(variables=("score",), alpha=0.05),
    )
    assert [row["name"] for row in report.variables] == ["score"]
    pd.testing.assert_frame_equal(base_frame, before_base)
    pd.testing.assert_frame_equal(current_frame, before_current)
    payload = report.as_payload()
    assert payload["baseline"]["name"] == "2024"
    assert payload["methodology"]["multiple_testing"]

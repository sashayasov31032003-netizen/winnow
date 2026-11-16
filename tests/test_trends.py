"""Тесты трендов по волнам."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from winnow.analysis.trends import TrendWave, analyze_trends
from winnow.core.dataset import Dataset


def _wave(year: int, shift: float, n: int = 50) -> Dataset:
    rng = np.random.default_rng(year)
    frame = pd.DataFrame(
        {
            "score": rng.normal(10 + shift, 1.5, n),
            "group": np.where(np.arange(n) % 3 == 0, "a", "b"),
        }
    )
    return Dataset.from_dataframe(frame, str(year))


def test_numeric_trend_and_significance():
    waves = [
        TrendWave(label="2022", dataset=_wave(2022, 0), year=2022),
        TrendWave(label="2023", dataset=_wave(2023, 1.5), year=2023),
        TrendWave(label="2024", dataset=_wave(2024, 3.0), year=2024),
    ]
    report = analyze_trends(waves)
    score = next(row for row in report.variables if row["name"] == "score")
    assert score["kind"] == "numeric"
    assert score["trend"]["slope"] > 0
    assert score["trend"]["p"] is not None
    assert score["p"] is not None and score["q"] is not None
    assert len(score["waves"]) == 3
    assert report.summary["n_waves"] == 3
    assert report.as_payload()["waves"][0]["label"] == "2022"


def test_categorical_trend_and_no_mutation():
    frames = []
    datasets = []
    for index, shift in enumerate([0, 1, 2]):
        dataset = _wave(2030 + index, shift)
        datasets.append(dataset)
        frames.append(dataset.frame.copy(deep=True))
    report = analyze_trends(
        [TrendWave(label=str(2030 + index), dataset=dataset, year=2030 + index) for index, dataset in enumerate(datasets)]
    )
    group = next(row for row in report.variables if row["name"] == "group")
    assert group["kind"] == "categorical"
    assert group["trend"]["chi2"] is not None
    assert "share_points" in group["trend"]
    for dataset, before in zip(datasets, frames):
        pd.testing.assert_frame_equal(dataset.frame, before)


def test_two_waves_are_allowed_but_no_trend_p():
    report = analyze_trends(
        [
            TrendWave(label="2024", dataset=_wave(2024, 0), year=2024),
            TrendWave(label="2025", dataset=_wave(2025, 2), year=2025),
        ]
    )
    score = next(row for row in report.variables if row["name"] == "score")
    assert score["p"] is None
    assert score["q"] is None


def test_no_common_variables_raise():
    a = Dataset.from_dataframe(pd.DataFrame({"x": [1, 2, 3]}), "a")
    b = Dataset.from_dataframe(pd.DataFrame({"y": [1, 2, 3]}), "b")
    c = Dataset.from_dataframe(pd.DataFrame({"z": [1, 2, 3]}), "c")
    with pytest.raises(ValueError, match="общих"):
        analyze_trends([TrendWave("a", a), TrendWave("b", b), TrendWave("c", c)])

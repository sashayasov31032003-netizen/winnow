"""Тесты инспектора качества: данные, модель, API и инструмент агента."""

from __future__ import annotations

import io
import os
import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-quality-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.analysis.quality import quality_report  # noqa: E402
from winnow.core.dataset import Dataset  # noqa: E402
from winnow.web.ai import store  # noqa: E402
from winnow.web.ai.config import load_settings  # noqa: E402
from winnow.web.ai.tools import ToolContext, execute_tool  # noqa: E402
from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def _registration(client, email: str = "quality@example.com") -> int:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": ""},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _upload(client) -> int:
    csv = "id,group,score\n" + "\n".join(
        f"{index},{'a' if index % 2 else 'b'},{10 + index % 5}"
        for index in range(1, 31)
    )
    response = client.post(
        "/api/datasets",
        files={"file": ("data.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


# ------------------------------------------------------------------ данные


def test_duplicate_rows_and_constant_are_found():
    dataset = Dataset.from_records(
        {
            "group": ["a", "b", "b", "b", "a"],
            "value": [1.0, 2.0, 2.0, 3.0, 4.0],
            "const": [1, 1, 1, 1, 1],
        }
    )
    report = quality_report(dataset)
    assert report.n_cases == 5
    assert report.duplicate_rows == 1
    assert "duplicate_rows" in _codes(report)
    assert "constant_variable" in _codes(report)
    assert not report.has_critical


def test_high_missing_is_reported_with_share():
    dataset = Dataset.from_records(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [None, None, None, 1.0, 2.0],
        }
    )
    report = quality_report(dataset)
    assert "high_missing" in _codes(report)
    issue = next(item for item in report.issues if item.code == "high_missing")
    assert issue.variables == ("b",)
    assert issue.values == {} or "b" in issue.details


def test_clean_data_has_no_critical_issues():
    rng = np.random.default_rng(7)
    dataset = Dataset.from_records(
        {
            "x": rng.normal(50, 10, 120).round(2).tolist(),
            "y": rng.normal(20, 4, 120).round(2).tolist(),
        }
    )
    report = quality_report(dataset)
    assert report.n_cases == 120
    assert report.duplicate_rows == 0
    assert not report.has_critical
    assert report.counts["critical"] == 0


def test_multicollinearity_and_influential_cases():
    rng = np.random.default_rng(11)
    x1 = rng.normal(10, 2, 150)
    x2 = x1 + rng.normal(0, 0.05, 150)
    y = 2.0 * x1 + rng.normal(0, 1, 150)
    frame = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
    dataset = Dataset.from_dataframe(frame)
    report = quality_report(dataset, target="y", predictors=["x1", "x2"])
    assert report.regression is not None
    assert report.regression.max_vif > 5
    assert "multicollinearity" in _codes(report) or "multicollinearity_note" in _codes(report)


def test_heteroscedasticity_is_detected():
    rng = np.random.default_rng(3)
    x = np.linspace(1, 100, 200)
    y = 2.0 * x + rng.normal(0, 0.8, 200) * x
    dataset = Dataset.from_dataframe(pd.DataFrame({"x": x, "y": y}))
    report = quality_report(dataset, target="y", predictors=["x"])
    assert report.regression is not None
    assert report.regression.breusch_pagan_p is not None
    assert report.regression.breusch_pagan_p < 0.05
    assert "heteroscedasticity" in _codes(report)


def test_regression_rejects_non_numeric_target():
    dataset = Dataset.from_records({"group": ["a", "b", "a"], "y": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError):
        quality_report(dataset, target="group", predictors=["y"])


# ------------------------------------------------------------------ HTTP и агент


def test_quality_endpoint_returns_report(client):
    _registration(client)
    dataset_id = _upload(client)
    response = client.post(
        f"/api/datasets/{dataset_id}/quality",
        json={"target": "", "predictors": []},
    )
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["n_cases"] == 30
    assert "counts" in report
    assert isinstance(report["issues"], list)


def test_quality_agent_tool_saves_run(client):
    user_id = _registration(client)
    dataset_id = _upload(client)
    context = ToolContext(
        user_id=user_id, dataset_id=dataset_id, settings=load_settings()
    )
    result = execute_tool(context, "check_quality", {})
    assert result["ok"] is True
    assert result["run_id"] > 0
    assert result["quality"]["counts"]["critical"] == 0
    assert result["tables"]

    saved = store.get_run(user_id, result["run_id"])
    assert saved["procedure"] == "quality"
    assert saved["payload"]["quality"]["n_cases"] == 30


def test_scenarios_endpoint_survives_numpy_values(client):
    """Коды групп приходят из pandas как numpy-числа: JSON не должен падать."""
    _registration(client)
    dataset_id = _upload(client)
    response = client.get(f"/api/datasets/{dataset_id}/scenarios")
    assert response.status_code == 200, response.text
    assert "scenarios" in response.json()

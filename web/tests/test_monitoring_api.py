"""API сравнения волн."""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import tempfile

import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-monitoring-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402

BASE_CSV = "score,group\n" + "\n".join(
    f"{10 + index % 4},{'a' if index % 2 == 0 else 'b'}" for index in range(1, 41)
)
CURRENT_CSV = "score,group\n" + "\n".join(
    f"{12 + index % 4},{'a' if index % 3 == 0 else 'b'}" for index in range(1, 41)
)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_work():
    yield
    engine.dispose()
    shutil.rmtree(_WORK, ignore_errors=True)


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def _register(client, email: str = "monitoring@example.com", invite: str = "") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": invite},
    )
    assert response.status_code == 201, response.text


def _upload(client, name: str, content: str) -> int:
    response = client.post(
        "/api/datasets",
        files={"file": (name, io.BytesIO(content.encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_monitoring_compare_returns_changes(client):
    _register(client)
    baseline = _upload(client, "2024.csv", BASE_CSV)
    current = _upload(client, "2025.csv", CURRENT_CSV)
    response = client.post(
        "/api/monitoring/compare",
        json={"baseline_id": baseline, "current_id": current, "alpha": 0.05},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    report = body["report"]
    assert report["baseline"]["n_cases"] == 40
    assert report["current"]["n_cases"] == 40
    assert report["baseline"]["name"] != report["current"]["name"]
    score = next(row for row in report["variables"] if row["name"] == "score")
    assert score["change"]["mean_diff"] > 0
    assert score["p"] is not None
    assert score["q"] is not None
    assert report["summary"]["compared_variables"] == 2


def test_monitoring_rejects_same_dataset_and_other_user(client):
    _register(client)
    baseline = _upload(client, "2024.csv", BASE_CSV)
    same = client.post(
        "/api/monitoring/compare",
        json={"baseline_id": baseline, "current_id": baseline},
    )
    assert same.status_code == 422

    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "other-monitoring@example.com", invite=invite)
    other = client.post(
        "/api/monitoring/compare",
        json={"baseline_id": baseline, "current_id": baseline + 1},
    )
    assert other.status_code == 404

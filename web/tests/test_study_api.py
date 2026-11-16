"""API исследований, волн и трендов."""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import tempfile

import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-study-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402


def _csv(offset: int) -> str:
    return "score,group\n" + "\n".join(
        f"{10 + offset + index % 3},{'a' if index % 2 == 0 else 'b'}"
        for index in range(1, 31)
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


def _register(client, email: str = "study@example.com", invite: str = "") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": invite},
    )
    assert response.status_code == 201, response.text


def _upload(client, name: str, offset: int) -> int:
    response = client.post(
        "/api/datasets",
        files={"file": (name, io.BytesIO(_csv(offset).encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_study_waves_and_trends(client):
    _register(client)
    study = client.post("/api/studies", json={"name": "Мониторинг 2022–2024"}).json()
    study_id = study["id"]
    ids = [_upload(client, f"{year}.csv", offset) for year, offset in [(2022, 0), (2023, 1), (2024, 2)]]
    for year, dataset_id in zip([2022, 2023, 2024], ids):
        response = client.post(
            f"/api/studies/{study_id}/waves",
            json={"dataset_id": dataset_id, "label": str(year), "year": year},
        )
        assert response.status_code == 200, response.text
    detail = client.get(f"/api/studies/{study_id}").json()
    assert len(detail["waves"]) == 3
    assert detail["waves"][0]["label"] == "2022"

    trends = client.post(f"/api/studies/{study_id}/trends", json={"alpha": 0.05})
    assert trends.status_code == 200, trends.text
    report = trends.json()["report"]
    assert report["summary"]["n_waves"] == 3
    score = next(row for row in report["variables"] if row["name"] == "score")
    assert score["kind"] == "numeric"
    assert score["trend"]["slope"] > 0

    duplicate = client.post(
        f"/api/studies/{study_id}/waves",
        json={"dataset_id": ids[0], "label": "дубль", "year": 2022},
    )
    assert duplicate.status_code == 409


def test_study_ownership(client):
    _register(client)
    study = client.post("/api/studies", json={"name": "Мой мониторинг"}).json()
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "other-study@example.com", invite=invite)
    response = client.get(f"/api/studies/{study['id']}")
    assert response.status_code == 404

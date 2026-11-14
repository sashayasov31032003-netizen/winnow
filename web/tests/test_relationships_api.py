"""API карты взаимосвязей: права, методы и структура ответа."""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import tempfile

import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-relations-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402

CSV = "x,y,group,city\n" + "\n".join(
    f"{index % 11},{2 + (index % 11) * 0.9 + (index % 3) * 0.2},"
    f"{'a' if index % 2 == 0 else 'b'},{'moscow' if index % 3 == 0 else 'other'}"
    for index in range(1, 61)
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


def _register(client, email: str = "relations@example.com", invite: str = "") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": invite},
    )
    assert response.status_code == 201, response.text


def _upload(client) -> int:
    response = client.post(
        "/api/datasets",
        files={"file": ("relations.csv", io.BytesIO(CSV.encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_relationship_map_returns_nodes_edges_and_summary(client):
    _register(client)
    dataset_id = _upload(client)
    response = client.post(
        f"/api/datasets/{dataset_id}/relationships",
        json={"method": "pearson", "max_variables": 20},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset_revision"]
    revision = client.get(f"/api/datasets/{dataset_id}/revision")
    assert revision.status_code == 200
    assert revision.json()["revision"] == body["dataset_revision"]
    assert {node["name"] for node in body["nodes"]} >= {"x", "y", "group", "city"}
    assert body["edges"]
    edge = next(item for item in body["edges"] if {item["source"], item["target"]} == {"x", "y"})
    assert edge["method"] == "pearson"
    assert edge["p"] is not None and edge["q"] is not None
    assert "recommendations" in body["summary"]


def test_relationship_map_rejects_unknown_method_and_other_user(client):
    _register(client)
    dataset_id = _upload(client)
    bad = client.post(
        f"/api/datasets/{dataset_id}/relationships",
        json={"method": "magic"},
    )
    assert bad.status_code == 422

    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "other-relations@example.com", invite=invite)
    other = client.post(
        f"/api/datasets/{dataset_id}/relationships",
        json={"method": "auto"},
    )
    assert other.status_code == 404

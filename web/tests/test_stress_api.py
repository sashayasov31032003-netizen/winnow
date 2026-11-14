"""API Research Stress Test: права, валидация и сохранение прогона."""

from __future__ import annotations

import io
import os
import pathlib
import shutil
import tempfile

import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-stress-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402

CSV = "y,x1,x2,control\n" + "\n".join(
    f"{2 + 1.2 * (index % 7) - 0.7 * (index % 3) + (index % 2) * 0.4},"
    f"{index % 7},{(index * 3) % 5},{index % 4}"
    for index in range(1, 61)
)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_work():
    """Убирает временную БД после закрытия движка, иначе Windows держит файл."""
    yield
    engine.dispose()
    shutil.rmtree(_WORK, ignore_errors=True)


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def _register(client, email: str = "stress@example.com", invite: str = "") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": invite},
    )
    assert response.status_code == 201, response.text


def _upload(client) -> int:
    response = client.post(
        "/api/datasets",
        files={"file": ("stress.csv", io.BytesIO(CSV.encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _payload(**overrides):
    data = {
        "target": "y",
        "predictors": ["x1", "x2"],
        "checks": [
            "diagnostics",
            "influence",
            "robust",
            "specifications",
            "bootstrap",
        ],
        "auto": False,
        "bootstrap": 30,
        "seed": 11,
        "confidence": 0.95,
        "alpha": 0.05,
        "add_controls": [],
    }
    data.update(overrides)
    return data


def test_stress_test_runs_and_is_saved(client):
    _register(client)
    dataset_id = _upload(client)
    response = client.post(
        f"/api/datasets/{dataset_id}/stress-test", json=_payload()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] > 0
    report = body["report"]
    assert report["run_id"] == body["run_id"]
    assert report["baseline"]["id"] == "baseline"
    assert report["baseline"]["n"] == 60
    assert "HC3" in report["robust"]
    assert report["bootstrap"]["valid"] > 0
    assert report["methodology"]["seed"] == 11

    saved = client.get(f"/api/stress-tests/{body['run_id']}")
    assert saved.status_code == 200, saved.text
    run = saved.json()["run"]
    assert run["procedure"] == "stress_test"
    assert run["payload"]["run_id"] == body["run_id"]
    assert run["params"]["bootstrap"] == 30


def test_stress_test_rejects_bad_target_and_checks(client):
    _register(client)
    dataset_id = _upload(client)
    bad = client.post(
        f"/api/datasets/{dataset_id}/stress-test",
        json=_payload(target="missing"),
    )
    assert bad.status_code == 422

    no_checks = client.post(
        f"/api/datasets/{dataset_id}/stress-test",
        json=_payload(auto=False, checks=[]),
    )
    assert no_checks.status_code == 422

    too_many = client.post(
        f"/api/datasets/{dataset_id}/stress-test",
        json=_payload(bootstrap=5000),
    )
    assert too_many.status_code == 422


def test_other_user_cannot_read_stress_test(client):
    _register(client, "first@example.com")
    dataset_id = _upload(client)
    response = client.post(
        f"/api/datasets/{dataset_id}/stress-test", json=_payload()
    )
    run_id = response.json()["run_id"]
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")

    _register(client, "second@example.com", invite=invite)
    other = client.get(f"/api/stress-tests/{run_id}")
    assert other.status_code == 404

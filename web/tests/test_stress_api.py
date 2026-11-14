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
    assert "result" in run["payload"]

    history = client.get(f"/api/datasets/{dataset_id}/stress-tests")
    assert history.status_code == 200
    assert history.json()["runs"][0]["run_id"] == body["run_id"]

    exported = client.get(f"/api/stress-tests/{body['run_id']}/export?format=html")
    assert exported.status_code == 200
    assert "text/html" in exported.headers["content-type"]
    assert "Research Stress Test" in exported.text

    for fmt in ("docx", "xlsx"):
        binary = client.get(f"/api/stress-tests/{body['run_id']}/export?format={fmt}")
        assert binary.status_code == 200, binary.text
        assert len(binary.content) > 1000


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


def test_excluded_rows_are_saved_and_compared(client):
    _register(client)
    dataset_id = _upload(client)
    payload = _payload(exclude_rows=[2, 4], bootstrap=20)
    response = client.post(f"/api/datasets/{dataset_id}/stress-test", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    scenario = next(
        item for item in body["report"]["scenarios"] if item["id"] == "exclude_rows"
    )
    assert scenario["n"] == 58
    assert body["report"]["config"]["exclude_rows"] == [2, 4]

    invalid = client.post(
        f"/api/datasets/{dataset_id}/stress-test",
        json=_payload(exclude_rows=[999]),
    )
    assert invalid.status_code == 422


def test_stress_challenge_is_saved_with_report(client):
    _register(client)
    dataset_id = _upload(client)
    payload = _payload(
        challenge={
            "hypothesis": "x1 положительно связан с y",
            "focal": "x1",
            "direction": "positive",
            "controls": ["control"],
        }
    )
    response = client.post(f"/api/datasets/{dataset_id}/stress-test", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    report = body["report"]
    assert report["challenge"] is not None
    assert report["challenge"]["focal"] == "x1"
    assert report["challenge"]["status"] in {
        "supported",
        "fragile",
        "contradicted",
        "insufficient",
    }
    assert report["challenge"]["checks"]

    run = client.get(f"/api/stress-tests/{body['run_id']}").json()["run"]
    assert run["params"]["challenge"]["hypothesis"].startswith("x1")


def test_bad_challenge_focal_returns_422(client):
    _register(client)
    dataset_id = _upload(client)
    response = client.post(
        f"/api/datasets/{dataset_id}/stress-test",
        json=_payload(
            challenge={
                "hypothesis": "Нет такого предиктора",
                "focal": "control",
                "direction": "positive",
                "controls": [],
            }
        ),
    )
    assert response.status_code == 422


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

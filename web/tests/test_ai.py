"""Тесты Research Intelligence: инструменты, агент, HTTP-слой.

Настоящая модель здесь не вызывается: провайдер подменяется сценарием. Это
принципиально — тест должен проверять наш цикл и наши числа, а не доступность
чужого API. Числа в результате инструмента сверяются с прямым расчётом движка,
чтобы «агент» не мог незаметно разойтись с отчётом.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import pathlib
import tempfile

import pytest

_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-ai-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")
os.environ.setdefault("WINNOW_AI_PROVIDER", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.stats.command import DescriptivesCommand  # noqa: E402
from winnow.stats.engine import execute  # noqa: E402
from winnow.web import storage  # noqa: E402
from winnow.web.ai import store  # noqa: E402
from winnow.web.ai.agent import run_turn  # noqa: E402
from winnow.web.ai.config import AISettings, load_settings  # noqa: E402
from winnow.web.ai.guardrails import (  # noqa: E402
    ToolArgumentsError,
    unverified_numbers,
)
from winnow.web.ai.provider import FakeProvider, Reply, ToolCall  # noqa: E402
from winnow.web.ai.tools import ToolContext, execute_tool  # noqa: E402
from winnow.web import ai_api  # noqa: E402
from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402

CSV = "\n".join(
    ["id,group,score"]
    + [f"{index},{'a' if index % 2 else 'b'},{10 + index % 3}" for index in range(1, 13)]
) + "\n"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def _register(client, email: str = "ai@example.com") -> int:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "invite": ""},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _second_user(client) -> None:
    """Заводит второго пользователя по приглашению первого."""
    invite = client.post("/api/invites").json()["code"]
    response = client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "secret123", "invite": invite},
    )
    assert response.status_code == 201, response.text


def _upload(client) -> int:
    response = client.post(
        "/api/datasets",
        files={"file": ("data.csv", io.BytesIO(CSV.encode()), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _context(user_id: int, dataset_id: int) -> ToolContext:
    return ToolContext(user_id=user_id, dataset_id=dataset_id, settings=load_settings())


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        data = [
            line[5:].strip()
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


# ------------------------------------------------------------------ инструменты


def test_schema_returns_variables_without_rows(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    result = execute_tool(_context(user_id, dataset_id), "get_dataset_schema", {})
    names = [item["name"] for item in result["variables"]]
    assert names == ["id", "group", "score"]
    assert result["dataset"]["ai_full_access"] is False
    assert "rows" not in result


def test_profile_reports_cases_and_roles(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    result = execute_tool(_context(user_id, dataset_id), "get_profile", {})
    assert result["n_cases"] == 12
    roles = {item["name"]: item["role"] for item in result["variables"]}
    assert roles["id"] == "идентификатор"
    assert roles["group"] == "категория"
    assert roles["score"] in {"показатель", "порядковая", "категория"}


def test_run_procedure_matches_engine_numbers(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    result = execute_tool(
        _context(user_id, dataset_id),
        "run_procedure",
        {"procedure": "descriptives", "values": {"variables": ["score"]}},
    )
    table = result["tables"][0]
    labels = [column for column in table["columns"]]
    mean_index = labels.index("Среднее")
    assert result["tables"][0]["rows"][0][mean_index] == pytest.approx(11.0)

    # Тот же расчёт напрямую через движок: числа обязаны совпасть.
    row = store.dataset_row(user_id, dataset_id)
    dataset = storage.load_dataset(row.path)
    expected = execute(DescriptivesCommand(dataset=dataset, variables=["score"]))
    expected_mean = expected.tables[0].rows[0][
        [column.label for column in expected.tables[0].columns].index("Среднее")
    ]
    assert result["tables"][0]["rows"][0][mean_index] == pytest.approx(
        float(expected_mean)
    )
    assert result["run_id"] > 0


def test_run_saved_and_readable_by_owner_only(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    result = execute_tool(
        _context(user_id, dataset_id),
        "run_procedure",
        {"procedure": "frequencies", "values": {"variables": ["group"]}},
    )
    run_id = result["run_id"]

    first = client.get(f"/api/analyses/{run_id}")
    assert first.status_code == 200
    assert first.json()["procedure"] == "frequencies"

    _second_user(client)
    foreign = client.get(f"/api/analyses/{run_id}")
    assert foreign.status_code == 404


def test_preview_is_denied_until_flag_is_set(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    context = _context(user_id, dataset_id)

    denied = execute_tool(context, "get_preview", {})
    assert denied["allowed"] is False

    client.patch(f"/api/datasets/{dataset_id}/ai-access", json={"allow": True})
    allowed = execute_tool(context, "get_preview", {"limit": 3})
    assert allowed["allowed"] is True
    assert len(allowed["preview"]["rows"]) == 3
    assert "score" in allowed["preview"]["rows"][0]


def test_arguments_outside_schema_are_rejected(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    with pytest.raises(ToolArgumentsError):
        execute_tool(
            _context(user_id, dataset_id),
            "run_procedure",
            {"procedure": "descriptives", "values": {}, "unknown": 1},
        )
    with pytest.raises(ToolArgumentsError):
        execute_tool(_context(user_id, dataset_id), "get_preview", {"limit": 999})


def test_forbidden_procedure_is_not_reachable(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    with pytest.raises(ToolArgumentsError):
        execute_tool(
            _context(user_id, dataset_id),
            "run_procedure",
            {"procedure": "compute", "values": {}},
        )


# ------------------------------------------------------------------ агент


def _scripted_provider() -> FakeProvider:
    return FakeProvider(
        [
            Reply(
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_procedure",
                        arguments={
                            "procedure": "descriptives",
                            "values": {"variables": ["score"]},
                        },
                    )
                ]
            ),
            Reply(text="Среднее по score посчитано, расчёт: [run:1]."),
        ]
    )


def test_agent_collects_run_and_persists_messages(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    conversation_id: int | None = None
    events: list[dict] = []

    async def run() -> None:
        nonlocal conversation_id
        async for event in run_turn(
            user_id=user_id,
            dataset_id=dataset_id,
            conversation_id=None,
            message="Посчитай описательные статистики по score",
            settings=AISettings(provider="fake", daily_turns=10),
            provider=_scripted_provider(),
        ):
            events.append(event)
            if event["type"] == "start":
                conversation_id = event["conversation_id"]

    asyncio.run(run())
    types = [event["type"] for event in events]
    assert types[:2] == ["start", "tool_call"]
    assert "run" in types
    assert types[-2:] == ["text", "done"]
    done = events[-1]
    assert done["runs"][0]["run_id"] > 0
    assert done["warnings"] == []

    detail = store.conversation_detail(user_id, conversation_id or 0)
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert "Среднее по score" in detail["messages"][1]["content"]
    assert detail["tool_calls"][0]["status"] == "ok"
    assert detail["tool_calls"][0]["run_id"] == done["runs"][0]["run_id"]


def test_agent_flags_numbers_without_calculation(client):
    user_id = _register(client)
    dataset_id = _upload(client)
    provider = FakeProvider(
        [
            Reply(
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_procedure",
                        arguments={
                            "procedure": "descriptives",
                            "values": {"variables": ["score"]},
                        },
                    )
                ]
            ),
            Reply(text="Среднее равно 99,5, p = 0,001."),
        ]
    )
    warnings: list[str] = []

    async def run() -> None:
        async for event in run_turn(
            user_id=user_id,
            dataset_id=dataset_id,
            conversation_id=None,
            message="Посчитай среднее",
            settings=AISettings(provider="fake", daily_turns=10),
            provider=provider,
        ):
            if event["type"] == "warning":
                warnings.append(event["message"])

    asyncio.run(run())
    assert warnings
    assert "99,5" in warnings[0] or "0,001" in warnings[0]


def test_number_check_accepts_values_from_payload():
    payload = {"run_id": 1, "tables": [{"rows": [[0.31, 16.5]]}]}
    assert unverified_numbers("p = 0,31, среднее 16,5", [payload]) == []
    assert unverified_numbers("p = 0,03", [payload]) == ["0,03"]


def test_number_check_understands_inequalities():
    payload = {"run_id": 1, "p": 0.0004}
    assert unverified_numbers("p < 0,001", [payload]) == []
    assert unverified_numbers("p < 0,0001", [payload]) == ["0,0001"]


# ------------------------------------------------------------------ HTTP / SSE


def _fake_settings(**overrides) -> AISettings:
    values = {"provider": "fake", "model": "fake", "daily_turns": 10}
    values.update(overrides)
    return AISettings(**values)


def test_chat_streams_events_and_saves_conversation(client, monkeypatch):
    user_id = _register(client)
    dataset_id = _upload(client)
    monkeypatch.setattr(ai_api, "settings_factory", lambda: _fake_settings())
    monkeypatch.setattr(
        ai_api, "provider_factory", lambda settings: _scripted_provider()
    )

    response = client.post(
        "/api/ai/chat",
        json={
            "dataset_id": dataset_id,
            "message": "Посчитай описательные статистики по score",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    types = [event["type"] for event in events]
    assert "tool_call" in types
    assert "run" in types
    assert "done" in types

    conversation_id = next(
        event["conversation_id"] for event in events if event["type"] == "start"
    )
    saved = client.get(f"/api/ai/conversations/{conversation_id}")
    assert saved.status_code == 200
    assert len(saved.json()["messages"]) == 2
    assert store.count_user_messages_today(user_id) == 1


def test_chat_respects_daily_quota(client, monkeypatch):
    _register(client)
    dataset_id = _upload(client)
    monkeypatch.setattr(
        ai_api, "settings_factory", lambda: _fake_settings(daily_turns=1)
    )
    monkeypatch.setattr(
        ai_api, "provider_factory", lambda settings: _scripted_provider()
    )

    first = client.post(
        "/api/ai/chat", json={"dataset_id": dataset_id, "message": "Первый"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/ai/chat", json={"dataset_id": dataset_id, "message": "Второй"}
    )
    assert second.status_code == 429
    assert "лимит" in second.json()["detail"].lower()


def test_config_never_exposes_key(client, monkeypatch):
    _register(client)
    monkeypatch.setattr(ai_api, "settings_factory", lambda: _fake_settings())
    response = client.get("/api/ai/config")
    assert response.status_code == 200
    payload = response.json()
    assert "api_key" not in payload
    assert payload["provider"] == "fake"
    assert payload["remaining"] == 10
    assert payload["data_policy"] == "aggregates"


def test_ai_access_flag_is_exposed_in_dataset_list(client):
    _register(client)
    dataset_id = _upload(client)
    before = client.get("/api/datasets").json()[0]
    assert before["ai_full_access"] is False

    updated = client.patch(
        f"/api/datasets/{dataset_id}/ai-access", json={"allow": True}
    )
    assert updated.status_code == 200
    after = client.get("/api/datasets").json()[0]
    assert after["ai_full_access"] is True


def test_foreign_dataset_is_not_visible(client):
    _register(client)
    dataset_id = _upload(client)
    _second_user(client)
    response = client.post(
        "/api/ai/chat", json={"dataset_id": dataset_id, "message": "Привет"}
    )
    assert response.status_code == 404

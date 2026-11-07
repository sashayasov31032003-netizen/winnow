"""Тесты опросов: конструктор, публичная ссылка и сохранение ответов.

Проверяется то, чего нет у наборов: структура, которую задаёт человек, и
приём ответов снаружи без входа. Правила «какой вопрос допустим» и «какой ответ
принять» живут в web/surveys.py, поэтому здесь они проверяются через HTTP -
так же, как ими пользуется интерфейс.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Настройки читаются при импорте приложения, поэтому переменные окружения
# выставляются до него: иначе тесты писали бы в рабочую базу.
_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-web-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from winnow.web import surveys  # noqa: E402
from winnow.web.core import (  # noqa: E402
    Answer,
    Base,
    Question,
    SessionLocal,
    Survey,
    SurveyResponse,
    engine,
)
from winnow.web.main import FRONTEND_DIST, app  # noqa: E402

#: Анкета со всеми типами вопросов: так один тест проверяет весь набор.
QUESTIONS = [
    {
        "kind": "single",
        "text": "Ваш пол",
        "required": True,
        "choices": ["Мужской", "Женский"],
    },
    {
        "kind": "multi",
        "text": "Источники",
        "required": False,
        "choices": ["ТВ", "Радио", "Интернет"],
    },
    {"kind": "number", "text": "Возраст", "required": True, "min": 14, "max": 100},
    {"kind": "scale", "text": "Оценка", "required": True, "min": 1, "max": 5},
    {"kind": "text", "text": "Комментарий", "required": False, "max_length": 100},
]


@pytest.fixture()
def client():
    """Чистая база, чистый клиент и сброшенный счётчик частоты на каждый тест."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    surveys.SUBMIT_LIMITER.reset()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def owner(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "secret123", "invite": ""},
    )
    assert response.status_code == 201, response.text
    return client


def _create(client, questions=None, **extra):
    payload = {
        "title": "Оценка курса",
        "description": "Короткий опрос",
        "questions": QUESTIONS if questions is None else questions,
        **extra,
    }
    response = client.post("/api/surveys", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client, survey_id: int):
    response = client.post(f"/api/surveys/{survey_id}/status", json={"status": "open"})
    assert response.status_code == 200, response.text
    return response.json()


def _public(client, slug: str):
    response = client.get(f"/api/public/surveys/{slug}")
    assert response.status_code == 200, response.text
    return response.json()


def _answers(payload: dict) -> list[dict]:
    """Заполняет все вопросы, кроме необязательного текста."""
    by_kind = {question["kind"]: question for question in payload["questions"]}
    choices = {
        kind: [choice["id"] for choice in question["choices"]]
        for kind, question in by_kind.items()
        if question["choices"]
    }
    return [
        {"question_id": by_kind["single"]["id"], "option_ids": [choices["single"][1]]},
        {"question_id": by_kind["multi"]["id"], "option_ids": choices["multi"][:2]},
        {"question_id": by_kind["number"]["id"], "value_number": 34},
        {"question_id": by_kind["scale"]["id"], "value_number": 4},
    ]


def _submit(client, slug: str, answers: list[dict]):
    return client.post(f"/api/public/surveys/{slug}/responses", json={"answers": answers})


# --------------------------------------------------------------- конструктор


def test_surveys_require_login(client):
    assert client.get("/api/surveys").status_code == 401
    assert client.post("/api/surveys", json={"title": "Опрос"}).status_code == 401
    assert client.put("/api/surveys/1", json={"title": "Опрос"}).status_code == 401
    assert client.delete("/api/surveys/1").status_code == 401


def test_created_survey_is_a_draft_with_a_random_link(owner):
    created = _create(owner)
    assert created["status"] == "draft"
    assert created["stored_status"] == "draft"
    # Случайный адрес - это защита: перебором чужие опросы не найти.
    assert len(created["slug"]) >= 10
    assert created["n_questions"] == len(QUESTIONS)
    assert created["can_edit"] is True
    # Варианты получили короткие номера, по которым хранятся ответы.
    single = created["questions"][0]
    assert [choice["id"] for choice in single["choices"]] == ["1", "2"]
    assert created["questions"][2]["min"] == 14
    assert created["questions"][3]["max"] == 5
    assert created["questions"][4]["max_length"] == 100


def test_builder_reports_bad_questions_in_russian(owner):
    cases = [
        ([{"kind": "single", "text": "", "choices": ["Да"]}], "не заполнен текст"),
        ([{"kind": "single", "text": "Вопрос", "choices": []}], "вариант"),
        ([{"kind": "matrix", "text": "Вопрос"}], "неизвестный тип"),
        (
            [{"kind": "number", "text": "Возраст", "min": 10, "max": 5}],
            "граница больше верхней",
        ),
        ([{"kind": "scale", "text": "Оценка", "min": 1, "max": 1}], "пустая"),
    ]
    for questions, expected in cases:
        response = owner.post(
            "/api/surveys", json={"title": "Проверка", "questions": questions}
        )
        assert response.status_code == 422, (questions, response.text)
        assert expected in response.json()["detail"].lower()


def test_empty_title_is_rejected(owner):
    response = owner.post("/api/surveys", json={"title": "   "})
    assert response.status_code == 422
    assert "название" in response.json()["detail"]


def test_cannot_publish_empty_survey(owner):
    created = _create(owner, questions=[])
    response = owner.post(f"/api/surveys/{created['id']}/status", json={"status": "open"})
    assert response.status_code == 422
    assert "вопрос" in response.json()["detail"]


def test_editing_before_answers_rewrites_questions(owner):
    created = _create(owner, questions=[QUESTIONS[0]])
    response = owner.put(
        f"/api/surveys/{created['id']}",
        json={
            "title": "Новое название",
            "description": "Другое описание",
            "allow_multiple": True,
            "questions": [QUESTIONS[0], QUESTIONS[1]],
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["title"] == "Новое название"
    assert saved["n_questions"] == 2
    assert saved["allow_multiple"] is True
    assert [question["text"] for question in saved["questions"]] == [
        "Ваш пол",
        "Источники",
    ]


# ------------------------------------------------------------ публичная часть


def test_public_link_is_hidden_until_published(owner):
    created = _create(owner)
    owner.post("/api/auth/logout")
    before = owner.get(f"/api/public/surveys/{created['slug']}")
    assert before.status_code == 404
    owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})
    _publish(owner, created["id"])
    owner.post("/api/auth/logout")

    payload = _public(owner, created["slug"])
    assert payload["title"] == "Оценка курса"
    assert payload["status"] == "open"
    assert len(payload["questions"]) == len(QUESTIONS)
    assert payload["already_answered"] is False


def test_unknown_link_reports_missing_survey(client):
    response = client.get("/api/public/surveys/нет-такого")
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_submission_is_saved_to_the_database(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")

    payload = _public(owner, slug)
    answers = _answers(payload)
    answers.append(
        {
            "question_id": payload["questions"][4]["id"],
            "value_text": "Курс понравился",
        }
    )
    response = _submit(owner, slug, answers)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "saved"

    # Главная проверка этапа: ответы лежат в таблицах, а не в памяти запроса.
    with SessionLocal() as db:
        survey = db.scalar(select(Survey).where(Survey.slug == slug))
        assert survey is not None
        responses = db.scalars(
            select(SurveyResponse).where(SurveyResponse.survey_id == survey.id)
        ).all()
        assert len(responses) == 1
        saved = db.scalars(
            select(Answer).where(Answer.response_id == responses[0].id)
        ).all()
        assert len(saved) == len(answers)
        by_question = {answer.question_id: answer for answer in saved}
        number = by_question[payload["questions"][2]["id"]]
        assert number.value_number == 34
        single = by_question[payload["questions"][0]["id"]]
        assert single.option_ids == ["2"]
        multi = by_question[payload["questions"][1]["id"]]
        assert multi.option_ids == ["1", "2"]
        text = by_question[payload["questions"][4]["id"]]
        assert text.value_text == "Курс понравился"
        # Вопросы тоже на месте: ответ ссылается на настоящий вопрос.
        assert db.scalar(select(func.count(Question.id))) == len(QUESTIONS)


def test_saved_answers_are_readable_by_the_owner(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    assert _submit(owner, slug, _answers(payload)).status_code == 201

    owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})
    page = owner.get(f"/api/surveys/{created['id']}/responses")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 1
    values = {item["question"]: item["value"] for item in body["responses"][0]["answers"]}
    # Человек видит метки вариантов, а не номера «1», «2».
    assert values["Ваш пол"] == "Женский"
    assert values["Источники"] == "ТВ, Радио"
    assert values["Возраст"] == "34"
    assert values["Оценка"] == "4"

    listing = owner.get("/api/surveys").json()
    assert listing[0]["n_responses"] == 1


def test_required_question_must_be_answered(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    answers = [item for item in _answers(payload) if item["question_id"] != payload["questions"][0]["id"]]

    response = _submit(owner, slug, answers)
    assert response.status_code == 422
    assert "Ваш пол" in response.json()["detail"]
    assert "обязательный" in response.json()["detail"]


def test_answer_must_match_the_question(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    single = payload["questions"][0]["id"]

    unknown_option = _submit(
        owner,
        slug,
        [{"question_id": single, "option_ids": ["99"]}],
    )
    assert unknown_option.status_code == 422
    assert "такого варианта" in unknown_option.json()["detail"]

    two_options = _submit(
        owner,
        slug,
        [{"question_id": single, "option_ids": ["1", "2"]}],
    )
    assert two_options.status_code == 422
    assert "только один" in two_options.json()["detail"]

    unknown_question = _submit(owner, slug, [{"question_id": 9999, "option_ids": ["1"]}])
    assert unknown_question.status_code == 422
    assert "Обновите страницу" in unknown_question.json()["detail"]


def test_number_and_scale_limits(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    number_id = payload["questions"][2]["id"]
    scale_id = payload["questions"][3]["id"]
    filled = _answers(payload)

    def replaced(question_id: int, **patch):
        """Полная анкета, но с одним подменённым ответом."""
        result = [dict(item) for item in filled]
        for item in result:
            if item["question_id"] == question_id:
                item.update(patch)
        return result

    too_young = _submit(owner, slug, replaced(number_id, value_number=5))
    assert too_young.status_code == 422
    assert "меньше" in too_young.json()["detail"]

    not_a_number = _submit(owner, slug, replaced(number_id, value_number="сорок"))
    assert not_a_number.status_code == 422
    assert "не число" in not_a_number.json()["detail"]

    half_point = _submit(owner, slug, replaced(scale_id, value_number=4.5))
    assert half_point.status_code == 422
    assert "целый балл" in half_point.json()["detail"]


def test_long_text_answer_is_rejected(owner):
    created = _create(
        owner,
        questions=[{"kind": "text", "text": "Комментарий", "max_length": 10}],
    )
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)

    response = _submit(
        owner,
        slug,
        [{"question_id": payload["questions"][0]["id"], "value_text": "о" * 60}],
    )
    assert response.status_code == 422
    assert "длиннее 10" in response.json()["detail"]


# --------------------------------------------------- один ответ на браузер


def test_second_answer_from_same_browser_is_refused(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    answers = _answers(payload)

    assert _submit(owner, slug, answers).status_code == 201
    again = _submit(owner, slug, answers)
    assert again.status_code == 409
    assert "уже отвечали" in again.json()["detail"]
    # И форма знает об этом заранее: человек не заполняет анкету зря.
    assert _public(owner, slug)["already_answered"] is True


def test_repeats_allowed_when_the_survey_permits_them(owner):
    created = _create(owner, allow_multiple=True)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    answers = _answers(payload)

    assert _submit(owner, slug, answers).status_code == 201
    assert _submit(owner, slug, answers).status_code == 201
    assert _public(owner, slug)["already_answered"] is False


def test_repeated_submissions_are_rate_limited(owner):
    created = _create(owner, allow_multiple=True)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)
    answers = _answers(payload)

    original = surveys.SUBMIT_LIMITER.limit
    surveys.SUBMIT_LIMITER.limit = 2
    try:
        assert _submit(owner, slug, answers).status_code == 201
        assert _submit(owner, slug, answers).status_code == 201
        limited = _submit(owner, slug, answers)
        assert limited.status_code == 429
        assert "Слишком много" in limited.json()["detail"]
    finally:
        surveys.SUBMIT_LIMITER.limit = original


# ------------------------------------------------------------- закрытие


def test_closed_survey_stops_accepting_answers(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    payload = _public(owner, slug)

    owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})
    closed = owner.post(f"/api/surveys/{created['id']}/status", json={"status": "closed"})
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    owner.post("/api/auth/logout")

    refused = _submit(owner, slug, _answers(payload))
    assert refused.status_code == 403
    assert "закрыт" in refused.json()["detail"]
    shown = _public(owner, slug)
    assert shown["status"] == "closed"
    # Вопросы закрытого опроса не отдаются: заполнять всё равно нечего.
    assert shown["questions"] == []


def test_close_date_in_the_past_closes_survey(owner):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    created = _create(owner, closes_at=past)
    assert created["status"] == "closed", "просроченный опрос уже не принимает ответы"
    response = owner.post(f"/api/surveys/{created['id']}/status", json={"status": "open"})
    assert response.status_code == 422
    assert "уже прошла" in response.json()["detail"]


def test_close_date_in_the_future_keeps_the_survey_open(owner):
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    created = _create(owner, closes_at=future)
    assert created["status"] == "draft"
    assert created["closes_at"] is not None
    _publish(owner, created["id"])
    assert owner.get(f"/api/surveys/{created['id']}").json()["status"] == "open"


# -------------------------------------------------- правка после ответов


def test_structure_is_frozen_after_the_first_answer(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    assert _submit(owner, slug, _answers(_public(owner, slug))).status_code == 201

    owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})
    frozen = owner.put(
        f"/api/surveys/{created['id']}",
        json={"title": "Другое", "questions": []},
    )
    assert frozen.status_code == 409
    assert "менять нельзя" in frozen.json()["detail"]
    # Читать структуру по-прежнему можно, и она помечена как зафиксированная.
    detail = owner.get(f"/api/surveys/{created['id']}").json()
    assert detail["can_edit"] is False
    assert detail["n_questions"] == len(QUESTIONS)


def test_survey_with_answers_is_not_deleted(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    slug = created["slug"]
    owner.post("/api/auth/logout")
    assert _submit(owner, slug, _answers(_public(owner, slug))).status_code == 201
    owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})

    response = owner.delete(f"/api/surveys/{created['id']}")
    assert response.status_code == 409
    assert "ответы" in response.json()["detail"]


def test_empty_survey_is_deleted(owner):
    created = _create(owner)
    assert owner.delete(f"/api/surveys/{created['id']}").status_code == 204
    assert owner.get(f"/api/surveys/{created['id']}").status_code == 404
    assert owner.get("/api/surveys").json() == []


# ---------------------------------------------------------- чужие опросы


def test_other_user_cannot_see_survey(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    invite = owner.post("/api/invites").json()["code"]
    owner.post("/api/auth/logout")
    assert (
        owner.post(
            "/api/auth/register",
            json={"email": "guest@example.com", "password": "secret123", "invite": invite},
        ).status_code
        == 201
    )

    # Чужой опрос отвечает «не найден», как и чужой набор: иначе можно узнать,
    # что такой опрос существует.
    assert owner.get(f"/api/surveys/{created['id']}").status_code == 404
    assert owner.get(f"/api/surveys/{created['id']}/responses").status_code == 404
    assert owner.delete(f"/api/surveys/{created['id']}").status_code == 404
    assert (
        owner.put(f"/api/surveys/{created['id']}", json={"title": "Мой"}).status_code
        == 404
    )
    assert owner.get("/api/surveys").json() == []
    # А публичная ссылка работает для всех: в этом и смысл опроса.
    assert owner.get(f"/api/public/surveys/{created['slug']}").status_code == 200


# ------------------------------------------------------------- страница


@pytest.mark.skipif(
    not (FRONTEND_DIST / "index.html").is_file(),
    reason="интерфейс не собран: страница /s/<slug> отдаётся из web/frontend/dist",
)
def test_public_page_is_served_for_the_short_link(owner):
    created = _create(owner)
    _publish(owner, created["id"])
    page = owner.get(f"/s/{created['slug']}")
    assert page.status_code == 200
    assert "<div id=\"root\">" in page.text
    # Вход не нужен: та же страница открывается и без сессии.
    owner.post("/api/auth/logout")
    assert owner.get(f"/s/{created['slug']}").status_code == 200

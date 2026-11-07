"""Тесты этапа 2: опрос превращается в набор, и на нём считается статистика.

Проверяется главное обещание плана: структура известна заранее, поэтому
переменные получают правильные метки и уровни измерения без догадок, а на
готовом наборе работают советчик и процедуры - как с обычным файлом.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

# Настройки читаются при импорте приложения, поэтому переменные окружения
# выставляются до него.
_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-web-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web import surveys  # noqa: E402
from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import app  # noqa: E402

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
    {"kind": "text", "text": "Комментарий", "required": False, "max_length": 200},
]

OWNER = {"email": "owner@example.com", "password": "secret123", "invite": ""}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    surveys.SUBMIT_LIMITER.reset()
    with TestClient(app) as test_client:
        yield test_client


def _register(client) -> None:
    assert client.post("/api/auth/register", json=OWNER).status_code == 201


def _login(client) -> None:
    response = client.post(
        "/api/auth/login", json={"email": OWNER["email"], "password": "secret123"}
    )
    assert response.status_code == 200, response.text


def _survey(client, questions=None) -> dict:
    """Черновик плюс публикация: дальше можно принимать ответы."""
    created = client.post(
        "/api/surveys",
        json={"title": "Курс", "questions": QUESTIONS if questions is None else questions},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert (
        client.post(
            f"/api/surveys/{payload['id']}/status", json={"status": "open"}
        ).status_code
        == 200
    )
    return payload


def _answers(questions: list[dict], index: int) -> list[dict]:
    """Ответ «респондента №index»: у чётных есть множественный выбор и текст."""
    by_kind = {question["kind"]: question for question in questions}
    choice_ids = {
        kind: [choice["id"] for choice in question["choices"]]
        for kind, question in by_kind.items()
        if question["choices"]
    }
    result = [
        {"question_id": by_kind["single"]["id"], "option_ids": [choice_ids["single"][index % 2]]},
        {"question_id": by_kind["number"]["id"], "value_number": 20 + index},
        {"question_id": by_kind["scale"]["id"], "value_number": 1 + index % 5},
    ]
    if index % 2 == 0:
        result.append(
            {
                "question_id": by_kind["multi"]["id"],
                "option_ids": choice_ids["multi"][: 1 + index % 3],
            }
        )
        result.append(
            {
                "question_id": by_kind["text"]["id"],
                "value_text": f"Ответ {index}",
            }
        )
    return result


def _collect(client, slug: str, count: int = 6) -> None:
    """Заполняет опрос count раз; сессия владельца восстанавливается в конце."""
    public = client.get(f"/api/public/surveys/{slug}")
    assert public.status_code == 200, public.text
    questions = public.json()["questions"]
    for index in range(count):
        # Чистые cookie - это как другой браузер: без повторов ответ не пройдёт.
        client.cookies.clear()
        response = client.post(
            f"/api/public/surveys/{slug}/responses",
            json={"answers": _answers(questions, index)},
        )
        assert response.status_code == 201, (index, response.text)
    client.cookies.clear()
    _login(client)


def _prepared(client, count: int = 6) -> dict:
    """Опрос с ответами и уже собранный из них набор."""
    _register(client)
    created = _survey(client)
    client.post("/api/auth/logout")
    _collect(client, created["slug"], count)
    built = client.post(f"/api/surveys/{created['id']}/dataset")
    assert built.status_code == 201, built.text
    return {"survey": created, "dataset": built.json()}


# ------------------------------------------------------------------ сборка


def test_build_requires_login(client):
    assert client.post("/api/surveys/1/dataset").status_code == 401


def test_build_requires_answers(client):
    _register(client)
    created = _survey(client)
    response = client.post(f"/api/surveys/{created['id']}/dataset")
    assert response.status_code == 422
    assert "Ответов пока нет" in response.json()["detail"]


def test_questions_become_variables_with_measures(client):
    built = _prepared(client)
    dataset = built["dataset"]
    assert dataset["name"] == "Опрос: Курс"
    assert dataset["n_cases"] == 6
    # 1 вопрос с вариантами + 3 отметки + число + шкала + текст.
    assert dataset["n_variables"] == 7

    detail = client.get(f"/api/datasets/{dataset['id']}").json()
    variables = {item["name"]: item for item in detail["variables"]}
    # Имя переменной - текст вопроса: в «Данных» видно, о чём столбец.
    assert list(variables) == [
        "Ваш пол",
        "Источники: ТВ",
        "Источники: Радио",
        "Источники: Интернет",
        "Возраст",
        "Оценка",
        "Комментарий",
    ]

    # Один вариант - категория, метка совпадает с именем и не дублируется.
    assert variables["Ваш пол"]["label"] == "Ваш пол"
    assert variables["Ваш пол"]["display"] == "Ваш пол"
    assert variables["Ваш пол"]["type"] == "numeric"
    assert variables["Ваш пол"]["measure"] == "nominal"

    # Несколько вариантов - по отметке на вариант, с меткой варианта.
    assert variables["Источники: ТВ"]["label"] == "Источники: ТВ"
    assert variables["Источники: Радио"]["measure"] == "nominal"

    # Число - количественная, шкала - порядковая: здесь догадок движка нет.
    assert variables["Возраст"]["measure"] == "scale"
    assert variables["Оценка"]["measure"] == "ordinal"

    # Текст - строковая переменная.
    assert variables["Комментарий"]["type"] == "string"
    assert variables["Комментарий"]["measure"] == "nominal"
    # Половина респондентов комментарий не писала: пропуски сохранены.
    assert variables["Комментарий"]["n_missing"] == 3
    assert variables["Источники: ТВ"]["n_missing"] == 3


def test_duplicate_question_texts_get_numbers(client):
    """Два одинаковых вопроса - два столбца, имена не слипаются."""
    questions = [
        {
            "kind": "single",
            "text": "Да или нет?",
            "required": True,
            "choices": ["Да", "Нет"],
        },
        {
            "kind": "single",
            "text": "Да или нет?",
            "required": True,
            "choices": ["Да", "Нет"],
        },
        {
            "kind": "multi",
            "text": "Да или нет?",
            "required": False,
            "choices": ["Да", "Нет"],
        },
    ]
    _register(client)
    created = _survey(client, questions=questions)
    client.post("/api/auth/logout")

    public = client.get(f"/api/public/surveys/{created['slug']}").json()
    singles = [q["id"] for q in public["questions"] if q["kind"] == "single"]
    multi = next(q["id"] for q in public["questions"] if q["kind"] == "multi")
    assert (
        client.post(
            f"/api/public/surveys/{created['slug']}/responses",
            json={
                "answers": [
                    {"question_id": singles[0], "option_ids": ["1"]},
                    {"question_id": singles[1], "option_ids": ["2"]},
                    {"question_id": multi, "option_ids": ["1"]},
                ]
            },
        ).status_code
        == 201
    )
    client.cookies.clear()
    _login(client)

    built = client.post(f"/api/surveys/{created['id']}/dataset")
    assert built.status_code == 201, built.text
    detail = client.get(f"/api/datasets/{built.json()['id']}").json()
    names = [item["name"] for item in detail["variables"]]
    assert names == [
        "Да или нет?",
        "Да или нет? (2)",
        "Да или нет?: Да",
        "Да или нет?: Нет",
    ]


def test_answers_land_in_the_right_cells(client):
    built = _prepared(client)
    preview = client.get(f"/api/datasets/{built['dataset']['id']}/preview").json()
    assert len(preview["rows"]) == 6
    first, second = preview["rows"][0], preview["rows"][1]

    # Коды вариантов: 1 - «Мужской», 2 - «Женский».
    assert first["Ваш пол"] == 1.0
    assert second["Ваш пол"] == 2.0
    # Отметки 1/0 по вариантам, а не строка «1;2».
    assert first["Источники: ТВ"] == 1.0
    assert first["Источники: Интернет"] == 0.0
    # Вопрос пропущен целиком - не ноль, а пропуск.
    assert second["Источники: ТВ"] is None
    # Число и шкала - как ввели.
    assert first["Возраст"] == 20.0
    assert second["Оценка"] == 2.0
    # Текст сохранён, у второго респондента его нет.
    assert first["Комментарий"] == "Ответ 0"
    assert second["Комментарий"] is None


def test_value_labels_are_in_the_report(client):
    """Метки вариантов доходят до отчёта: в частотах видно «Мужской», а не 1."""
    built = _prepared(client)
    report = client.post(
        f"/api/datasets/{built['dataset']['id']}/run",
        json={"procedure": "frequencies", "values": {"variables": ["Ваш пол"]}},
    )
    assert report.status_code == 200, report.text
    html = report.json()["html"]
    assert "Мужской" in html and "Женский" in html


def test_built_dataset_can_be_researched(client):
    """Проверка этапа: советчик предлагает исследования, отчёт считается.

    Ответов десять, а не два: советчик предлагает парные исследования только
    начиная с восьми случаев (MIN_PAIR_CASES), и на крошечной выборке проверка
    ничего бы не доказала.
    """
    built = _prepared(client, count=10)
    dataset_id = built["dataset"]["id"]
    assert built["dataset"]["n_cases"] == 10

    scenarios = client.get(f"/api/datasets/{dataset_id}/scenarios").json()
    assert scenarios["cases"] == 10
    assert scenarios["variables"] == 7
    assert len(scenarios["scenarios"]) >= 2, "советчику есть что предложить"
    # Есть исследование про связь двух переменных, а не только «описать выборку».
    assert any(
        scenario["procedure"] in ("crosstabs", "ttest", "correlations", "linear_regression")
        for scenario in scenarios["scenarios"]
    )

    descriptives = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "values": {"variables": ["Возраст"]}},
    )
    assert descriptives.status_code == 200, descriptives.text
    assert "<table" in descriptives.json()["html"]

    crosstabs = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={
            "procedure": "crosstabs",
            "values": {"row_vars": ["Ваш пол"], "col_vars": ["Оценка"]},
        },
    )
    assert crosstabs.status_code == 200, crosstabs.text
    assert crosstabs.json()["n_tables"] >= 1

    # Набор ведёт себя как обычный: его можно скачать и построить по нему график.
    download = client.get(f"/api/datasets/{dataset_id}/download?format=csv")
    assert download.status_code == 200
    assert "Источники: ТВ" in download.text


# ------------------------------------------------------- повторная сборка


def test_rebuild_reuses_the_dataset_and_takes_new_answers(client):
    built = _prepared(client, count=3)
    first_id = built["dataset"]["id"]
    assert built["dataset"]["n_cases"] == 3

    # Пришёл ещё один ответ - набор пересобирается, а не плодит копию.
    client.post("/api/auth/logout")
    _collect(client, built["survey"]["slug"], count=1)
    again = client.post(f"/api/surveys/{built['survey']['id']}/dataset")
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first_id
    assert again.json()["n_cases"] == 4

    listing = client.get("/api/datasets").json()
    assert len(listing) == 1, "в «Данных» не появилось копии «Опрос: …»"

    preview = client.get(f"/api/datasets/{first_id}/preview").json()
    assert len(preview["rows"]) == 4


def test_deleted_dataset_is_built_again(client):
    built = _prepared(client, count=2)
    first_id = built["dataset"]["id"]
    assert client.delete(f"/api/datasets/{first_id}").status_code == 204
    assert client.get(f"/api/datasets/{first_id}").status_code == 404

    # Ссылка с опроса снята при удалении, поэтому сборка начинается заново:
    # набор снова появляется и снова читается.
    again = client.post(f"/api/surveys/{built['survey']['id']}/dataset")
    assert again.status_code == 201, again.text
    assert again.json()["n_cases"] == 2
    assert again.json()["original_filename"] == f"survey-{built['survey']['slug']}.winnow"
    preview = client.get(f"/api/datasets/{again.json()['id']}/preview").json()
    assert len(preview["rows"]) == 2


def test_other_user_cannot_build(client):
    _register(client)
    created = _survey(client)
    client.post("/api/auth/logout")
    _collect(client, created["slug"], count=2)
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "guest@example.com", "password": "secret123", "invite": invite},
        ).status_code
        == 201
    )
    # Чужой опрос не виден даже как «нет прав»: только «не найден».
    assert client.post(f"/api/surveys/{created['id']}/dataset").status_code == 404

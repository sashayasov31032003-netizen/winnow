"""Тесты HTTP-слоя веб-приложения.

Проверяется то, что нельзя проверить в движке: вход и права, изоляция наборов
между пользователями и разбор загруженного файла. Статистика здесь не считается -
она уже покрыта 434 тестами движка, и дублировать их не нужно.
"""

from __future__ import annotations

import io
import os
import tempfile
import pathlib

import pytest

# Настройки читаются при импорте приложения, поэтому переменные окружения
# выставляются до него: иначе тесты писали бы в рабочую базу.
_WORK = pathlib.Path(tempfile.mkdtemp(prefix="winnow-web-tests-"))
os.environ.setdefault("WINNOW_DB_URL", f"sqlite:///{_WORK / 'test.db'}")
os.environ.setdefault("WINNOW_DATA", str(_WORK / "data"))
os.environ.setdefault("WINNOW_INVITE_ONLY", "1")

from fastapi.testclient import TestClient  # noqa: E402

from winnow.web.core import Base, engine  # noqa: E402
from winnow.web.main import FRONTEND_DIST, app  # noqa: E402

#: Небольшая анкета: пол, возраст и вопрос с несколькими ответами.
CSV_ROWS = [
    '"1. Ваш пол","2. Возраст","10. Источники"',
    '"1. Мужской","20","2. Радио"',
    '"2. Женский","21","1. Телевидение;2. Радио"',
    '"1. Мужской","22","1. Телевидение;2. Радио"',
    '"2. Женский","23","2. Радио"',
    '"1. Мужской","24","1. Телевидение;2. Радио"',
    '"2. Женский","25","1. Телевидение;2. Радио"',
    '"1. Мужской","26","2. Радио"',
    '"2. Женский","27","1. Телевидение;2. Радио"',
    '"1. Мужской","28","1. Телевидение;2. Радио"',
    '"2. Женский","29","2. Радио"',
    '"1. Мужской","30","1. Телевидение;2. Радио"',
    '"2. Женский","31","1. Телевидение;2. Радио"',
    '"1. Мужской","32","2. Радио"',
    '"2. Женский","33","1. Телевидение;2. Радио"',
    '"1. Мужской","34","1. Телевидение;2. Радио"',
]
CSV = "\n".join(CSV_ROWS) + "\n"


@pytest.fixture()
def client():
    """Чистая база и чистый клиент на каждый тест."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def _register(client, email: str, password: str = "secret123", invite: str = ""):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "invite": invite},
    )


def _upload(client, name: str = "survey.csv", content: str = CSV):
    return client.post(
        "/api/datasets",
        files={"file": (name, io.BytesIO(content.encode("utf-8")), "text/csv")},
    )


# ------------------------------------------------------------------ здоровье


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.skipif(
    not (FRONTEND_DIST / "index.html").is_file(),
    reason="интерфейс не собран: страницы отдаются из web/frontend/dist",
)
def test_site_pages_are_served(client):
    """Корень - рассказ о платформе, /app - рабочее место.

    Оба адреса отдают один собранный интерфейс: маршрут разбирает JavaScript.
    Без отдельного /app корень пришлось бы делить между главной и рабочим
    местом, а это разные вещи.
    """
    for path in ("/", "/app"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert page.headers["content-type"].startswith("text/html"), path
        assert '<div id="root">' in page.text, path


# --------------------------------------------------------------- регистрация


def test_first_user_registers_without_invite(client):
    """Первому пользователю приглашение не нужно: иначе его некому выдать."""
    response = _register(client, "owner@example.com")
    assert response.status_code == 201
    assert response.json()["email"] == "owner@example.com"
    # И он сразу вошёл: cookie выставлена.
    assert client.get("/api/auth/me").status_code == 200


def test_second_user_needs_invite(client):
    _register(client, "owner@example.com")
    client.post("/api/auth/logout")

    denied = _register(client, "guest@example.com")
    assert denied.status_code == 403
    assert "приглашени" in denied.json()["detail"]

    client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": "secret123"}
    )
    invite = client.post("/api/invites").json()["code"]

    allowed = _register(client, "guest@example.com", invite=invite)
    assert allowed.status_code == 201


def test_invite_cannot_be_used_twice(client):
    _register(client, "owner@example.com")
    invite = client.post("/api/invites").json()["code"]
    assert _register(client, "a@example.com", invite=invite).status_code == 201
    assert _register(client, "b@example.com", invite=invite).status_code == 403


def test_duplicate_email_is_rejected(client):
    assert _register(client, "same@example.com").status_code == 201
    again = _register(client, "same@example.com")
    assert again.status_code == 409


def test_short_password_is_rejected(client):
    response = _register(client, "x@example.com", password="123")
    assert response.status_code in (400, 422)


def test_login_with_wrong_password(client):
    _register(client, "user@example.com")
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": "user@example.com", "password": "wrong-pass"}
    )
    assert response.status_code == 401
    # Сообщение не должно подсказывать, существует ли такой адрес.
    assert "Неверный адрес или пароль" in response.json()["detail"]


# ------------------------------------------------------------------- наборы


def test_upload_and_read_dataset(client):
    _register(client, "user@example.com")
    created = _upload(client)
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["n_cases"] == 15
    assert payload["n_variables"] == 3
    assert payload["name"] == "survey"

    listing = client.get("/api/datasets").json()
    assert len(listing) == 1

    detail = client.get(f"/api/datasets/{payload['id']}").json()
    names = [item["name"] for item in detail["variables"]]
    assert "1. Ваш пол" in names
    assert detail["variables"][0]["display"]


def test_preview_returns_rows(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]

    preview = client.get(f"/api/datasets/{dataset_id}/preview").json()
    assert preview["columns"] == ["1. Ваш пол", "2. Возраст", "10. Источники"]
    assert len(preview["rows"]) == 15
    assert preview["rows"][0]["1. Ваш пол"] == "1. Мужской"


def test_scenarios_are_offered(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]

    payload = client.get(f"/api/datasets/{dataset_id}/scenarios").json()
    assert payload["cases"] == 15
    assert payload["variables"] == 3
    assert payload["scenarios"], "советчику есть что предложить"
    # У сценария есть готовые параметры: фронтенд запускает его без диалога.
    for scenario in payload["scenarios"]:
        assert "procedure" in scenario and "params" in scenario


def test_other_user_cannot_see_dataset(client):
    _register(client, "first@example.com")
    dataset_id = _upload(client).json()["id"]
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "second@example.com", invite=invite)

    # Чужой набор отвечает «не найдено», а не «нет прав»: иначе можно узнать,
    # что такой набор существует.
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404
    assert client.get(f"/api/datasets/{dataset_id}/preview").status_code == 404
    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 404
    assert client.get("/api/datasets").json() == []


def test_anonymous_cannot_use_api(client):
    assert client.get("/api/datasets").status_code == 401
    assert _upload(client).status_code == 401


def test_broken_file_is_reported_not_crashing(client):
    _register(client, "user@example.com")
    response = client.post(
        "/api/datasets",
        files={"file": ("bad.csv", io.BytesIO(b"\xff\xfe\x00 not a table"), "text/csv")},
    )
    assert response.status_code == 422
    assert "Не удалось прочитать файл" in response.json()["detail"]


def test_logout_stops_access(client):
    _register(client, "user@example.com")
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/datasets").status_code == 401


def test_delete_dataset(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404
    assert client.get("/api/datasets").json() == []


# ------------------------------------------------------------ запуск процедур


def _scenario_params(client, dataset_id: int) -> dict:
    payload = client.get(f"/api/datasets/{dataset_id}/scenarios").json()
    assert payload["scenarios"], "советчику есть что предложить"
    # Берётся первый предложенный сценарий: какие именно найдутся, зависит от
    # данных, а проверяется здесь сам запуск процедуры.
    return payload["scenarios"][0]


def test_run_descriptives_returns_report(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    scenario = _scenario_params(client, dataset_id)

    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": scenario["procedure"], "params": scenario["params"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["n_tables"] >= 1
    assert "<table" in payload["html"], "отчёт приходит готовым HTML"
    # Выводы простыми словами приходят отдельным списком: на маленьком наборе
    # их может не быть (связь незначима), поэтому проверяется структура.
    assert isinstance(payload["conclusions"], list)
    assert isinstance(payload["warnings"], list)


def test_run_rejects_compute_and_recode(client):
    """Выражения извне не выполняются: список процедур закрытый."""
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    for procedure in ("compute", "recode", "graph"):
        response = client.post(
            f"/api/datasets/{dataset_id}/run",
            json={"procedure": procedure, "params": {}},
        )
        assert response.status_code == 403, procedure


def test_run_validates_parameters(client):
    """Неверные параметры - ответ 422 с понятным текстом, а не падение."""
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "params": {"variables": []}},
    )
    assert response.status_code == 422
    assert "переменн" in response.json()["detail"].lower()


def test_run_unknown_procedure(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "нет-такой", "params": {}},
    )
    assert response.status_code == 403


def test_run_requires_login(client):
    response = client.post("/api/datasets/1/run", json={"procedure": "descriptives", "params": {}})
    assert response.status_code == 401


def test_run_other_user_dataset_is_hidden(client):
    _register(client, "first@example.com")
    dataset_id = _upload(client).json()["id"]
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "second@example.com", invite=invite)

    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "params": {"variables": ["2. Возраст"]}},
    )
    assert response.status_code == 404


# ---------------------------------------------------------- список процедур


def test_procedures_list_marks_blocked(client):
    _register(client, "user@example.com")
    items = client.get("/api/procedures").json()
    keys = {item["key"]: item for item in items}
    assert len(items) == 14, "все процедуры настольной версии"
    assert keys["ttest"]["allowed"] is True
    assert keys["descriptives"]["allowed"] is True
    # Выражения извне не выполняются.
    assert keys["compute"]["allowed"] is False
    assert keys["recode"]["allowed"] is False


def test_procedure_schema_describes_form(client):
    _register(client, "user@example.com")
    schema = client.get("/api/procedures/ttest").json()
    assert schema["title"] == "t-критерий"
    fields = {field["name"]: field for field in schema["fields"]}
    assert "test_vars" in fields and "group_var" in fields
    assert fields["test_vars"]["filter"] == "numeric"
    assert fields["test_vars"]["kind"] == "variable_list"
    assert fields["group_var"]["filter"] == "categorical"
    # У вида критерия есть варианты выбора - из них фронтенд сделает список.
    assert fields["kind"]["choices"], "выбор вида критерия"


def test_unknown_procedure_schema(client):
    _register(client, "user@example.com")
    assert client.get("/api/procedures/нет-такой").status_code == 404


def test_run_from_form_values(client):
    """Ручной запуск: значения формы собираются тем же описанием, что в окне."""
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "values": {"variables": ["2. Возраст"]}},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["n_tables"] >= 1
    assert "<table" in payload["html"]


def test_run_form_rejects_expression_procedures(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "compute", "values": {"target": "x", "expression": "1"}},
    )
    assert response.status_code == 403


# ------------------------------------------------------------ правка данных


def _patch_cells(client, dataset_id: int, edits: list[dict], **extra):
    return client.patch(
        f"/api/datasets/{dataset_id}/cells", json={"edits": edits, **extra}
    )


def test_edit_cell_changes_value_and_saves(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]

    response = _patch_cells(
        client, dataset_id, [{"row": 0, "column": "2. Возраст", "value": "99"}]
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 1
    assert response.json()["rows"][0]["2. Возраст"] == 99

    # Изменение сохранено в файл набора, а не только в ответе.
    preview = client.get(f"/api/datasets/{dataset_id}/preview").json()
    assert preview["rows"][0]["2. Возраст"] == 99


def test_edit_text_cell(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = _patch_cells(
        client, dataset_id, [{"row": 1, "column": "1. Ваш пол", "value": "не указан"}]
    )
    assert response.status_code == 200
    assert response.json()["rows"][1]["1. Ваш пол"] == "не указан"


def test_edit_accepts_comma_as_decimal_separator(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = _patch_cells(
        client, dataset_id, [{"row": 2, "column": "2. Возраст", "value": "41,5"}]
    )
    assert response.status_code == 200
    assert response.json()["rows"][2]["2. Возраст"] == 41.5


def test_edit_rejects_text_in_numeric_column(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = _patch_cells(
        client, dataset_id, [{"row": 0, "column": "2. Возраст", "value": "сорок"}]
    )
    assert response.status_code == 422
    assert "не число" in response.json()["detail"]


def test_edit_rejects_unknown_column_and_row(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    assert _patch_cells(client, dataset_id, [{"row": 0, "column": "нет", "value": "1"}]).status_code == 422
    assert _patch_cells(client, dataset_id, [{"row": 9999, "column": "2. Возраст", "value": "1"}]).status_code == 422


def test_edit_limits_batch_and_requires_login(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    many = [{"row": 0, "column": "2. Возраст", "value": "1"}] * 501
    assert _patch_cells(client, dataset_id, many).status_code == 413

    client.post("/api/auth/logout")
    assert _patch_cells(client, dataset_id, [{"row": 0, "column": "2. Возраст", "value": "1"}]).status_code == 401


def test_edit_other_user_dataset_is_hidden(client):
    _register(client, "first@example.com")
    dataset_id = _upload(client).json()["id"]
    invite = client.post("/api/invites").json()["code"]
    client.post("/api/auth/logout")
    _register(client, "second@example.com", invite=invite)
    response = _patch_cells(client, dataset_id, [{"row": 0, "column": "2. Возраст", "value": "1"}])
    assert response.status_code == 404


def test_preview_offset_pages(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    first = client.get(f"/api/datasets/{dataset_id}/preview?limit=5&offset=0").json()
    second = client.get(f"/api/datasets/{dataset_id}/preview?limit=5&offset=5").json()
    assert first["offset"] == 0 and second["offset"] == 5
    assert first["rows"] != second["rows"], "вторая страница - другие строки"


# ---------------------------------------------------------------- выгрузка


def _export(client, dataset_id: int, fmt: str, values: dict):
    return client.post(
        f"/api/datasets/{dataset_id}/export",
        json={"procedure": "descriptives", "values": values, "format": fmt},
    )


def test_export_word_and_excel(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]

    word = _export(client, dataset_id, "docx", {"variables": ["2. Возраст"]})
    assert word.status_code == 200, word.text
    assert "wordprocessingml" in word.headers["content-type"]
    assert word.content[:2] == b"PK", "docx - это zip-контейнер"
    assert len(word.content) > 1000
    assert "attachment" in word.headers["content-disposition"]

    excel = _export(client, dataset_id, "xlsx", {"variables": ["2. Возраст"]})
    assert excel.status_code == 200
    assert "spreadsheetml" in excel.headers["content-type"]
    assert excel.content[:2] == b"PK"


def test_export_html_contains_report(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    html = _export(client, dataset_id, "html", {"variables": ["2. Возраст"]})
    assert html.status_code == 200
    text = html.text
    assert "<table" in text, "таблицы отчёта на месте"
    assert "Простыми словами" in text, "и блок объяснения"


def test_export_rejects_unknown_format_and_blocked_procedure(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    assert _export(client, dataset_id, "pdf", {"variables": ["2. Возраст"]}).status_code == 422
    blocked = client.post(
        f"/api/datasets/{dataset_id}/export",
        json={"procedure": "compute", "values": {}, "format": "docx"},
    )
    assert blocked.status_code == 403


def test_export_requires_login(client):
    response = client.post(
        "/api/datasets/1/export",
        json={"procedure": "descriptives", "values": {"variables": ["x"]}, "format": "html"},
    )
    assert response.status_code == 401


# ------------------------------------------------------------------ графики


def test_charts_list_and_svg(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    kinds = [item["key"] for item in client.get("/api/charts").json()]
    assert kinds == ["histogram", "boxplot", "scatter", "bar", "pie", "line"]

    response = client.post(
        f"/api/datasets/{dataset_id}/chart",
        json={
            "values": {
                "kind": "histogram",
                "variables": ["2. Возраст"],
                "category": None,
                "bins": 0,
                "show_normal": False,
                "show_mean": False,
                "title": "",
            }
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["svg"].startswith("<svg"), "приходит готовая картинка"
    assert payload["svg"].rstrip().endswith("</svg>")
    assert "N = 15" in payload["caption"]


def test_boxplot_groups_by_category(client):
    """Категория у ящика должна давать подписи групп, а не игнорироваться."""
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/chart",
        json={
            "values": {
                "kind": "boxplot",
                "variables": ["2. Возраст"],
                "category": "1. Ваш пол",
                "title": "",
            }
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Мужской" in payload["svg"]
    assert "Женский" in payload["svg"]
    assert "групп: 2" in payload["caption"]


def test_bar_chart_needs_only_category(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/chart",
        json={
            "values": {
                "kind": "bar",
                "variables": [],
                "category": "1. Ваш пол",
            }
        },
    )
    assert response.status_code == 200, response.text


def test_chart_without_variables_is_reported(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/chart",
        json={"values": {"kind": "histogram", "variables": []}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_chart_requires_login(client):
    response = client.post("/api/datasets/1/chart", json={"values": {}})
    assert response.status_code == 401


# --------------------------------------------- вопросы с несколькими ответами


def test_multi_answer_detected_and_split(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]

    found = client.get(f"/api/datasets/{dataset_id}/multi-answer").json()
    assert found["count"] >= 1, "в данных есть ответы через «;»"
    assert found["items"][0]["summary"]

    split = client.post(f"/api/datasets/{dataset_id}/multi-answer/split")
    assert split.status_code == 200, split.text
    payload = split.json()
    assert payload["n_created"] >= 2, "по переменной на каждый вариант"
    assert payload["n_variables_after"] > payload["n_variables_before"]
    assert "отметк" in payload["report"].lower() or "разбит" in payload["report"].lower()
    names = [item["name"] for item in payload["variables"]]
    assert any("_" in name for name in names), "новые переменные вида q10_1"


def test_multi_answer_split_twice_reports_nothing_to_do(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    assert client.post(f"/api/datasets/{dataset_id}/multi-answer/split").status_code == 200
    again = client.post(f"/api/datasets/{dataset_id}/multi-answer/split")
    assert again.status_code == 422
    assert "не найдено" in again.json()["detail"]


def test_multi_answer_requires_login(client):
    assert client.get("/api/datasets/1/multi-answer").status_code == 401
    assert client.post("/api/datasets/1/multi-answer/split").status_code == 401


# ------------------------------------------------------- скачивание набора


def test_download_dataset_in_three_formats(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    # CSV пишется с BOM и со служебными строками метаданных переменных: так файл
    # читается обратно вместе с метками и уровнем измерения.
    formats = {"csv": b"\xef\xbb\xbf", "xlsx": b"PK", "sav": b"$FL2"}
    for fmt, magic in formats.items():
        response = client.get(f"/api/datasets/{dataset_id}/download?format={fmt}")
        assert response.status_code == 200, (fmt, response.text)
        assert response.content.startswith(magic), fmt
        assert "attachment" in response.headers["content-disposition"]


def test_download_reflects_edits(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    _patch_cells(client, dataset_id, [{"row": 0, "column": "2. Возраст", "value": "77"}])
    csv = client.get(f"/api/datasets/{dataset_id}/download?format=csv").text
    # Первая строка начинается с BOM, поэтому её тоже нужно снять перед разбором.
    data_lines = [line for line in csv.lstrip("\ufeff").splitlines() if not line.startswith("#")]
    assert "77" in data_lines[1], "в файле правка, а не исходное значение"


def test_download_rejects_unknown_format(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    assert client.get(f"/api/datasets/{dataset_id}/download?format=pdf").status_code == 422


def test_download_requires_login(client):
    assert client.get("/api/datasets/1/download?format=csv").status_code == 401


# ------------------------------------------- разбиение по группам и веса


def test_split_by_group_doubles_tables(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    values = {"variables": ["2. Возраст"]}

    plain = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "values": values},
    ).json()
    split = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={"procedure": "descriptives", "values": values, "split_by": "1. Ваш пол"},
    )
    assert split.status_code == 200, split.text
    body = split.json()
    # Таблиц становится больше и в отчёте видны обе группы: расчёт идёт по
    # каждой отдельно, а не по всем случаям вместе.
    assert body["n_tables"] > plain["n_tables"]
    assert "Мужской" in body["html"] and "Женский" in body["html"]
    # Выводы простыми словами тоже приходят - по каждому разбиению отдельно.
    assert body["conclusions"], "при разбиении объяснения не должны пропадать"
    assert any(
        "Мужской" in item["text"] or "Женский" in item["text"]
        for item in body["conclusions"]
    )


def test_split_by_unknown_variable_is_reported(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={
            "procedure": "descriptives",
            "values": {"variables": ["2. Возраст"]},
            "split_by": "нет такой",
        },
    )
    assert response.status_code == 422
    assert "нет в наборе" in response.json()["detail"]


def test_weights_are_accepted(client):
    _register(client, "user@example.com")
    dataset_id = _upload(client).json()["id"]
    response = client.post(
        f"/api/datasets/{dataset_id}/run",
        json={
            "procedure": "frequencies",
            "values": {"variables": ["1. Ваш пол"]},
            "weight": "2. Возраст",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["n_tables"] >= 1


# ------------------------------------------------- импорт по ссылке (защита)


def test_import_rejects_internal_and_bad_links(client):
    _register(client, "user@example.com")
    # Ссылки на собственную сеть запрещены: иначе сервер можно заставить
    # скачивать чужие внутренние адреса.
    for url in (
        "http://127.0.0.1:8000/api/health",
        "http://localhost/secret.csv",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/data.csv",
        "http://10.0.0.5/data.csv",
    ):
        response = client.post("/api/datasets/import", json={"url": url})
        assert response.status_code == 422, url
        assert response.json()["detail"]


def test_import_requires_login(client):
    response = client.post("/api/datasets/import", json={"url": "https://example.com/a.csv"})
    assert response.status_code == 401

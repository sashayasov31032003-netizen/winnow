"""Самопроверка веб-версии Winnow: полная цепочка на реальных файлах.

Зачем: после каждой правки человек проверяет руками вход, загрузку, переменные,
процедуры, графики и выгрузки - и находит поломки по одной. Этот скрипт проходит
тот же путь за несколько секунд и показывает, что именно сломалось.

Запуск (сервер должен быть запущен)::

    web\\check.cmd
    web\\check.cmd "E:\\Down\\67.csv\\67.csv"
    web\\check.cmd --email мой@mail.ru --password мойпароль

Код возврата 1, если найдены проблемы - удобно для автозапуска.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("WINNOW_CHECK_URL", "http://127.0.0.1:8000").rstrip("/")

#: Что проверять, если файлы не указаны: всё, что найдётся на месте.
DEFAULT_FILES = (
    r"E:\Down\учебный (2).sav",
    r"E:\Down\67.csv\67.csv",
    r"E:\Down\67 (Ответы) (3).xlsx",
)

problems: list[str] = []


def note(ok: bool, text: str, detail: str = "") -> None:
    print(("  ok   " if ok else "  ОШИБКА ") + text + ("" if ok else f" — {detail}"))
    if not ok:
        problems.append(f"{text}: {detail}")


def request(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.status, response.read(), response.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as error:
        return error.code, error.read(), []
    except urllib.error.URLError as error:
        print(f"\nСервер не отвечает по адресу {BASE}: {error.reason}")
        print("Запустите web\\run.cmd и повторите.")
        raise SystemExit(2)


def json_request(method: str, path: str, payload: dict, cookie: str = ""):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    status, body, cookies = request(method, path, json.dumps(payload).encode(), headers)
    try:
        return status, json.loads(body or b"{}"), cookies
    except json.JSONDecodeError:
        return status, {}, cookies


def sign_in(email: str, password: str) -> str:
    """Входит, а если такого нет - регистрирует. Возвращает cookie сессии."""
    status, payload, cookies = json_request(
        "POST", "/api/auth/register", {"email": email, "password": password, "invite": ""}
    )
    if status == 403:
        status, payload, cookies = json_request(
            "POST", "/api/auth/login", {"email": email, "password": password}
        )
        if status != 200:
            print("\nНа сервере уже есть пользователи, регистрация по приглашению.")
            print("Укажите свой аккаунт:  web\\check.cmd --email адрес --password пароль")
            raise SystemExit(2)
    if status not in (200, 201):
        print(f"\nНе удалось войти: {status} {payload.get('detail', '')}")
        raise SystemExit(2)
    if not cookies:
        print("\nРегистрация прошла, но cookie сессии не пришла.")
        raise SystemExit(2)
    return cookies[0].split(";")[0]


def upload(cookie: str, path: pathlib.Path) -> dict:
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    status, body, _ = request(
        "POST",
        "/api/datasets",
        head + path.read_bytes() + tail,
        {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Cookie": cookie,
        },
    )
    if status != 201:
        raise RuntimeError(f"загрузка {status}: {body[:200]!r}")
    return json.loads(body)


def check_file(cookie: str, path: pathlib.Path, verbose: bool) -> None:
    print(f"\n{path.name}")
    dataset = upload(cookie, path)
    dataset_id = dataset["id"]
    print(f"  файл: {dataset['n_cases']} случаев, {dataset['n_variables']} переменных")

    # 1. Переменные
    status, body, _ = request("GET", f"/api/datasets/{dataset_id}", None, {"Cookie": cookie})
    variables = json.loads(body)["variables"] if status == 200 else []
    note(len(variables) == dataset["n_variables"], f"переменных отдано {len(variables)}")

    # 2. Подсказки советчика
    status, body, _ = request(
        "GET", f"/api/datasets/{dataset_id}/scenarios", None, {"Cookie": cookie}
    )
    scenarios = json.loads(body).get("scenarios", []) if status == 200 else []
    note(status == 200 and bool(scenarios), f"подсказок советчика {len(scenarios)}")

    # 3. Каждая подсказка выполняется
    for scenario in scenarios:
        status, body, _ = request(
            "POST",
            f"/api/datasets/{dataset_id}/run",
            json.dumps(
                {"procedure": scenario["procedure"], "params": scenario["params"]}
            ).encode(),
            {"Content-Type": "application/json", "Cookie": cookie},
        )
        detail = "" if status == 200 else str(json.loads(body or b"{}").get("detail", ""))[:90]
        note(status == 200, f"подсказка «{scenario['title']}»", detail)

    # 4. Сопряжённость с двумя столбцами (проверка нескольких пар)
    categorical = [item["name"] for item in variables if item["n_unique"] <= 6]
    if len(categorical) >= 3:
        status, body, _ = request(
            "POST",
            f"/api/datasets/{dataset_id}/run",
            json.dumps(
                {
                    "procedure": "crosstabs",
                    "values": {
                        "row_vars": [categorical[0]],
                        "col_vars": categorical[1:3],
                        "count": True,
                        "row_percent": True,
                        "chi_square": True,
                        "phi_cramers_v": True,
                    },
                }
            ).encode(),
            {"Content-Type": "application/json", "Cookie": cookie},
        )
        result = json.loads(body or b"{}")
        note(
            status == 200 and result.get("n_tables", 0) >= 6,
            f"сопряжённость: две пары, таблиц {result.get('n_tables', 0)}",
            str(result.get("detail", ""))[:90],
        )

    # 5. График
    numeric = [item["name"] for item in variables if item["type"] == "numeric"]
    if numeric:
        status, body, _ = request(
            "POST",
            f"/api/datasets/{dataset_id}/chart",
            json.dumps(
                {
                    "values": {
                        "kind": "histogram",
                        "variables": [numeric[0]],
                        "category": None,
                        "bins": 0,
                        "show_normal": True,
                        "show_mean": True,
                        "title": "",
                    }
                }
            ).encode(),
            {"Content-Type": "application/json", "Cookie": cookie},
        )
        result = json.loads(body or b"{}")
        size = len(result.get("svg", ""))
        note(status == 200 and size > 500, f"гистограмма: {size} байт SVG")

    # 6. Выгрузки
    for fmt in ("csv", "sav", "xlsx"):
        status, body, _ = request(
            "GET", f"/api/datasets/{dataset_id}/download?format={fmt}", None, {"Cookie": cookie}
        )
        note(status == 200 and len(body) > 100, f"скачивание {fmt.upper()}: {len(body)} байт")

    # 7. Отчёт файлом
    if scenarios:
        status, body, _ = request(
            "POST",
            f"/api/datasets/{dataset_id}/export",
            json.dumps(
                {
                    "procedure": scenarios[0]["procedure"],
                    "params": scenarios[0]["params"],
                    "format": "docx",
                }
            ).encode(),
            {"Content-Type": "application/json", "Cookie": cookie},
        )
        note(status == 200 and body[:2] == b"PK", f"отчёт Word: {len(body)} байт")

    # 8. Уборка: набор удаляем, чтобы не копить мусор
    status, _, _ = request("DELETE", f"/api/datasets/{dataset_id}", None, {"Cookie": cookie})
    note(status == 204, "удаление набора", str(status))


def main() -> int:
    parser = argparse.ArgumentParser(description="Самопроверка веб-версии Winnow")
    parser.add_argument("files", nargs="*", help="файлы данных; по умолчанию - известные")
    parser.add_argument("--email", default=os.environ.get("WINNOW_CHECK_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("WINNOW_CHECK_PASSWORD", "secret123"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    files = [pathlib.Path(item) for item in args.files] or [
        pathlib.Path(item) for item in DEFAULT_FILES if pathlib.Path(item).exists()
    ]
    if not files:
        print("Не нашёл файлов для проверки. Укажите их: web\\check.cmd \"путь\\файл.csv\"")
        return 2

    email = args.email or f"check-{uuid.uuid4().hex[:6]}@example.com"
    print(f"Сервер: {BASE}")
    print(f"Аккаунт: {email}")
    status, body, _ = request("GET", "/api/health")
    if status != 200:
        print("Сервер не отвечает. Запустите web\\run.cmd")
        return 2
    print("Сервер работает")

    cookie = sign_in(email, args.password)

    for path in files:
        if not path.exists():
            note(False, f"файл {path.name}", "не найден")
            continue
        try:
            check_file(cookie, path, args.verbose)
        except Exception as error:  # noqa: BLE001 - проверка не должна падать целиком
            note(False, f"проверка {path.name}", f"{type(error).__name__}: {error}")

    print()
    if problems:
        print(f"ПРОБЛЕМ: {len(problems)}")
        for item in problems:
            print(f"  • {item}")
        return 1
    print("Проблем не найдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

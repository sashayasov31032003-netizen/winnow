"""Проверка живого сервера без браузера: регистрация, загрузка файла, советчик.

Нужна, чтобы убедиться, что всё работает, не разбираясь в странице /docs: она
сделана для программистов, а здесь одна команда делает весь путь целиком.

Запуск (сервер должен быть уже запущен)::

    web\\check.cmd "E:\\Down\\67.csv\\67.csv"
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"


def _request(method: str, path: str, *, data: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            cookies = response.headers.get_all("Set-Cookie") or []
            return response.status, body, cookies
    except urllib.error.HTTPError as error:
        return error.code, error.read(), []


def _json(method: str, path: str, payload: dict):
    status, body, cookies = _request(
        method,
        path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return status, json.loads(body or b"{}"), cookies


def _multipart(path: pathlib.Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    content = path.read_bytes()
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + content + tail, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    args = sys.argv[1:]
    path = pathlib.Path(args[0] if args else r"E:\Down\67.csv\67.csv")
    email = args[1] if len(args) > 1 else f"test-{uuid.uuid4().hex[:6]}@example.com"
    password = args[2] if len(args) > 2 else "secret123"
    if not path.exists():
        print(f"Файл не найден: {path}")
        return 1

    status, body, cookies = _request("GET", "/api/health")
    if status != 200:
        print("Сервер не отвечает. Запустите web\\run.cmd и повторите.")
        return 1
    print(f"1. Сервер работает: {json.loads(body)['status']}")

    status, payload, cookies = _json(
        "POST", "/api/auth/register", {"email": email, "password": password, "invite": ""}
    )

    if status == 403:
        # На сервере уже есть пользователи, и регистрация идёт по приглашению.
        status, payload, cookies = _json(
            "POST", "/api/auth/login", {"email": email, "password": password}
        )
        if status != 200:
            print("2. На сервере уже есть пользователи, регистрация по приглашению.")
            print("   Передайте свои адрес и пароль:")
            print(f'     web\\check.cmd "{path}" мой@mail.ru мойпароль')
            print("   Или попросите код приглашения у того, кто уже зарегистрирован.")
            return 2
        print(f"2. Вошли как {email}")
    elif status == 409:
        status, payload, cookies = _json(
            "POST", "/api/auth/login", {"email": email, "password": password}
        )
        if status != 200:
            print(f"   Пользователь есть, но пароль не подошёл: {payload}")
            print(f'   Запустите так: web\\check.cmd "{path}" {email} ваш_пароль')
            return 1
        print(f"2. Вошли как {email}")
    elif status == 201:
        print(f"2. Пользователь создан: {email}")
    else:
        print(f"   Регистрация не удалась: {status} {payload}")
        return 1

    cookie = cookies[0].split(";")[0] if cookies else ""
    if not cookie:
        print("   Cookie сессии не получена")
        return 1

    data, content_type = _multipart(path)
    status, body, _ = _request(
        "POST",
        "/api/datasets",
        data=data,
        headers={"Content-Type": content_type, "Cookie": cookie},
    )
    if status != 201:
        print(f"3. Загрузка не удалась: {status} {body[:300]}")
        return 1
    dataset = json.loads(body)
    print(
        f"3. Файл «{path.name}» загружен: набор {dataset['id']}, "
        f"{dataset['n_cases']} случаев, {dataset['n_variables']} переменных"
    )

    status, body, _ = _request(
        "GET", f"/api/datasets/{dataset['id']}/scenarios", headers={"Cookie": cookie}
    )
    payload = json.loads(body or b"{}")
    print(f"4. Советчик: сценариев {len(payload.get('scenarios', []))}")
    for scenario in payload.get("scenarios", [])[:5]:
        print(f"     • {scenario['title']} — {scenario['question']}")

    status, body, _ = _request(
        "GET", f"/api/datasets/{dataset['id']}/preview", headers={"Cookie": cookie}
    )
    preview = json.loads(body or b"{}")
    print(f"5. Предпросмотр: {len(preview.get('rows', []))} строк, колонок {len(preview.get('columns', []))}")
    if preview.get("columns"):
        print("     колонки: " + ", ".join(name[:28] for name in preview["columns"][:4]) + " …")

    print("\nВсё работает: сервер, вход, чтение файла и советчик.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Точка входа веб-приложения.

Запуск для разработки::

    web\\.venv\\Scripts\\python -m uvicorn winnow.web.main:app --reload --port 8000

Фронтенд во время разработки живёт отдельно (Vite, порт 5173) и обращается к
этому серверу; поэтому в разработке разрешён CORS с этого адреса.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import pathlib
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from winnow.web.ai_api import router as ai_router
from winnow.web.api import router
from winnow.web.core import SECRET, init_db
from winnow.web.monitoring_api import router as monitoring_router
from winnow.web.relationships_api import router as relationships_router
from winnow.web.stress_api import router as stress_router
from winnow.web.study_api import router as study_router

#: Собранный интерфейс (npm run build в web/frontend).
FRONTEND_DIST = (
    pathlib.Path(sys._MEIPASS) / "web" / "frontend" / "dist"
    if getattr(sys, "frozen", False)
    else pathlib.Path(__file__).resolve().parents[3] / "web" / "frontend" / "dist"
)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Таблицы создаются при старте: для диплома этого достаточно,
        # при публичном сервисе схема будет меняться через миграции.
        init_db()
        # Подпись сессий общим ключом из репозитория означает, что любую cookie
        # можно подделать. Для локальной работы это допустимо, для публичного
        # доступа - нет, поэтому предупреждаем прямо при запуске.
        if SECRET == "dev-secret-please-change":
            print()
            print("  ВНИМАНИЕ: WINNOW_SECRET не задан.")
            print("  Для публичного доступа задайте свой: set WINNOW_SECRET=<длинная строка>")
            print()
        yield

    app = FastAPI(
        title="Winnow",
        version="0.2.0",
        description="Статистический анализ данных: веб-версия",
        lifespan=lifespan,
    )

    # В разработке фронтенд на другом порту; в собранном виде он отдаётся этим же
    # сервером, и CORS не нужен. Список адресов задаётся настройкой, чтобы не
    # открывать API всему интернету.
    origins = os.environ.get(
        "WINNOW_CORS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in origins if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    # Research Intelligence подключается отдельным роутером: чат, диалоги,
    # сохранённые расчёты и разрешение на сырые данные.
    app.include_router(ai_router)
    # Research Stress Test: отдельный отчёт и сохранение прогона.
    app.include_router(stress_router)
    # Карта взаимосвязей: корреляции и меры связи.
    app.include_router(relationships_router)
    # Мониторинг: сравнение двух волн исследования.
    app.include_router(monitoring_router)
    # Исследования, волны и тренды.
    app.include_router(study_router)

    def app_page() -> FileResponse:
        """Отдаёт собранный интерфейс: маршрут внутри разбирает JavaScript.

        Адресов у приложения три: ``/`` - рассказ о платформе и выбор пути,
        ``/app`` - рабочее место (данные и опросы), ``/s/<slug>`` - публичная
        анкета. Все три отдают один и тот же собранный интерфейс, поэтому
        статические файлы подключены ниже одним каталогом.
        """
        index = FRONTEND_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=404,
                detail="Интерфейс не собран: выполните npm run build в web/frontend",
            )
        return FileResponse(index)

    @app.get("/app", include_in_schema=False)
    def workspace_page() -> FileResponse:
        """Рабочее место: опросы и анализ.

        Отдельный адрес нужен, чтобы корень сайта оставался рассказом о
        платформе: человек сначала понимает, куда попал, и уже потом выбирает
        «создать опрос» или «исследовать данные».
        """
        return app_page()

    # Публичная форма отвечает по короткому адресу /s/<slug>: именно эту ссылку
    # отправляют людям, и вход для неё не нужен.
    @app.get("/s/{slug}", include_in_schema=False)
    def public_survey_page(slug: str) -> FileResponse:
        return app_page()

    # Интерфейс подключается последним: иначе он перехватил бы /api.
    # Если сборки нет, сервер работает только как API.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app()


__all__ = ["app", "create_app"]

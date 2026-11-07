"""HTTP-слой Research Intelligence: чат, диалоги, расчёты, доступ к данным.

Здесь только транспорт и проверки прав. Сам цикл — в `ai/agent.py`, инструменты
— в `ai/tools.py`, хранение — в `ai/store.py`. Такой разрез позволяет тестировать
агента без HTTP, а HTTP — без настоящей модели.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from winnow.web.ai import store
from winnow.web.ai.agent import run_turn
from winnow.web.ai.config import AISettings, describe, load_settings
from winnow.web.ai.guardrails import AIGuardError, check_message
from winnow.web.ai.provider import AIProviderError, create_provider
from winnow.web.core import User
from winnow.web.security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

#: Фабрики вынесены в атрибуты модуля, чтобы тесты подменяли провайдера и
#: настройки, не трогая окружение процесса.
settings_factory = load_settings
provider_factory = create_provider


class ChatIn(BaseModel):
    dataset_id: int
    message: str
    conversation_id: int | None = None


class AccessIn(BaseModel):
    allow: bool


def _settings() -> AISettings:
    return settings_factory()


def _provider(settings: AISettings):
    try:
        return provider_factory(settings)
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _sse(event: dict[str, Any]) -> str:
    return (
        f"event: {event.get('type', 'message')}\n"
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    )


async def _stream(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield _sse(event)
    except AIGuardError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001 - поток не должен рваться без события
        logger.exception("Research agent failed")
        yield _sse(
            {
                "type": "error",
                "message": (
                    "Внутренняя ошибка агента. Попробуйте ещё раз; если повторяется — "
                    f"сообщите администратору ({type(exc).__name__})."
                ),
            }
        )


@router.get("/ai/config")
def ai_config(user: User = Depends(current_user)) -> dict[str, Any]:
    """Что клиенту можно знать: модель, лимит, остаток. Ключа здесь нет."""
    settings = _settings()
    used = store.count_user_messages_today(user.id)
    payload = describe(settings)
    payload["used_today"] = used
    payload["remaining"] = max(0, settings.daily_turns - used)
    if settings.provider == "fake":
        payload["note"] = (
            "Демо-режим: модель не подключена, запросы наружу не уходят. "
            "Для работы агента задайте WINNOW_AI_KEY на сервере."
        )
    elif not settings.enabled:
        payload["note"] = (
            "Не хватает настроек провайдера: проверьте ключ, каталог (для Yandex) "
            "и имя модели."
        )
    else:
        payload["note"] = (
            "ИИ видит схему, профиль и агрегаты. Сырые строки — только при "
            "явном разрешении у набора."
        )
    return payload


@router.post("/ai/chat")
async def ai_chat(
    payload: ChatIn, user: User = Depends(current_user)
) -> StreamingResponse:
    """Один ход диалога, потоком событий (SSE)."""
    settings = _settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503,
            detail="ИИ не настроен: задайте WINNOW_AI_KEY на сервере.",
        )

    try:
        check_message(payload.message)
    except AIGuardError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    used = store.count_user_messages_today(user.id)
    if used >= settings.daily_turns:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Дневной лимит сообщений исчерпан ({settings.daily_turns}). "
                "Он защищает бесплатный доступ от случайного перерасхода; "
                "попробуйте завтра."
            ),
        )

    try:
        store.dataset_row(user.id, payload.dataset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Набор не найден") from exc

    provider = _provider(settings)

    return StreamingResponse(
        _stream(
            run_turn(
                user_id=user.id,
                dataset_id=payload.dataset_id,
                conversation_id=payload.conversation_id,
                message=payload.message,
                settings=settings,
                provider=provider,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ai/conversations")
def list_ai_conversations(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"conversations": store.list_conversations(user.id)}


@router.get("/ai/conversations/{conversation_id}")
def get_ai_conversation(
    conversation_id: int, user: User = Depends(current_user)
) -> dict[str, Any]:
    try:
        return store.conversation_detail(user.id, conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Диалог не найден") from exc


@router.delete("/ai/conversations/{conversation_id}", status_code=204)
def delete_ai_conversation(
    conversation_id: int, user: User = Depends(current_user)
) -> None:
    try:
        store.delete_conversation(user.id, conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Диалог не найден") from exc


@router.get("/analyses/{run_id}")
def get_analysis(run_id: int, user: User = Depends(current_user)) -> dict[str, Any]:
    try:
        return store.get_run(user.id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Расчёт не найден") from exc


@router.get("/datasets/{dataset_id}/analyses")
def list_analyses(
    dataset_id: int, user: User = Depends(current_user)
) -> dict[str, Any]:
    try:
        store.dataset_row(user.id, dataset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Набор не найден") from exc
    return {"runs": store.list_runs(user.id, dataset_id)}


@router.patch("/datasets/{dataset_id}/ai-access")
def set_ai_access(
    dataset_id: int, payload: AccessIn, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Разрешение ИИ видеть сырые строки — отдельным действием человека."""
    try:
        return store.set_ai_access(user.id, dataset_id, payload.allow)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Набор не найден") from exc


__all__ = ["router", "settings_factory", "provider_factory"]

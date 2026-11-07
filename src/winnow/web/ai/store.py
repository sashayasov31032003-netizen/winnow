"""Хранение диалогов, вызовов инструментов и расчётов.

Каждая функция открывает свою сессию. Это намеренно: агент работает в
асинхронном цикле, инструменты выполняются в потоках, и передавать один
SQLAlchemy-сеанс между потоками нельзя. Короткая сессия на операцию снимает
вопрос и не держит соединение, пока модель думает.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from winnow.web.core import (
    AIConversation,
    AIMessage,
    AIToolCall,
    AnalysisRun,
    Dataset,
    SessionLocal,
    utcnow,
)
from winnow.web.storage import dataset_revision


def _day_start() -> datetime:
    """Начало текущих суток UTC в том же виде, в каком их хранит база."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


# ---------------------------------------------------------------- диалоги


def create_conversation(
    user_id: int, dataset_id: int | None, title: str = ""
) -> int:
    with SessionLocal() as session:
        row = AIConversation(
            user_id=user_id,
            dataset_id=dataset_id,
            title=(title or "Новый диалог")[:120],
        )
        session.add(row)
        session.commit()
        return int(row.id)


def get_conversation(user_id: int, conversation_id: int) -> AIConversation:
    with SessionLocal() as session:
        row = session.get(AIConversation, conversation_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Диалог не найден")
        # Отсоединяем от сессии: дальше нужны только скалярные поля.
        session.expunge(row)
        return row


def list_conversations(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = (
            session.query(AIConversation)
            .filter(AIConversation.user_id == user_id)
            .order_by(AIConversation.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "title": row.title,
                "dataset_id": row.dataset_id,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
            for row in rows
        ]


def conversation_detail(user_id: int, conversation_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(AIConversation, conversation_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Диалог не найден")
        messages = (
            session.query(AIMessage)
            .filter(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.id)
            .all()
        )
        calls = (
            session.query(AIToolCall)
            .filter(AIToolCall.conversation_id == conversation_id)
            .order_by(AIToolCall.id)
            .all()
        )
        return {
            "id": row.id,
            "title": row.title,
            "dataset_id": row.dataset_id,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "messages": [
                {
                    "id": item.id,
                    "role": item.role,
                    "content": item.content,
                    "model": item.model,
                    "created_at": item.created_at.isoformat()
                    if item.created_at
                    else "",
                }
                for item in messages
            ],
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "status": call.status,
                    "error": call.error,
                    "run_id": call.run_id,
                    "duration_ms": call.duration_ms,
                }
                for call in calls
            ],
        }


def delete_conversation(user_id: int, conversation_id: int) -> None:
    with SessionLocal() as session:
        row = session.get(AIConversation, conversation_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Диалог не найден")
        session.delete(row)
        session.commit()


def touch_conversation(conversation_id: int) -> None:
    with SessionLocal() as session:
        row = session.get(AIConversation, conversation_id)
        if row is not None:
            row.updated_at = utcnow()
            session.commit()


# ---------------------------------------------------------------- сообщения


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    *,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> int:
    with SessionLocal() as session:
        row = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        session.add(row)
        conversation = session.get(AIConversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = utcnow()
        session.commit()
        return int(row.id)


def history(conversation_id: int, limit: int = 12) -> list[dict[str, str]]:
    """Последние сообщения для контекста модели (без вызовов инструментов)."""
    with SessionLocal() as session:
        rows = (
            session.query(AIMessage)
            .filter(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.id.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [
            {"role": row.role, "content": row.content}
            for row in rows
            if row.role in {"user", "assistant"} and row.content
        ]


def add_tool_call(
    conversation_id: int, name: str, arguments: dict[str, Any]
) -> int:
    with SessionLocal() as session:
        row = AIToolCall(
            conversation_id=conversation_id,
            name=name,
            arguments=arguments,
            status="running",
        )
        session.add(row)
        session.commit()
        return int(row.id)


def finish_tool_call(
    call_id: int,
    *,
    status: str,
    error: str = "",
    run_id: int | None = None,
    duration_ms: int = 0,
) -> None:
    with SessionLocal() as session:
        row = session.get(AIToolCall, call_id)
        if row is None:
            return
        row.status = status
        row.error = (error or "")[:2000]
        row.run_id = run_id
        row.duration_ms = duration_ms
        session.commit()


def count_user_messages_today(user_id: int) -> int:
    """Сколько сообщений человек отправил агенту за текущие сутки (UTC)."""
    with SessionLocal() as session:
        return (
            session.query(AIMessage)
            .join(AIConversation, AIMessage.conversation_id == AIConversation.id)
            .filter(
                AIConversation.user_id == user_id,
                AIMessage.role == "user",
                AIMessage.created_at >= _day_start(),
            )
            .count()
        )


# ---------------------------------------------------------------- расчёты


def save_run(
    *,
    user_id: int,
    dataset_id: int,
    dataset_path: str,
    procedure: str,
    title: str,
    params: dict[str, Any],
    payload: dict[str, Any],
    duration_ms: int = 0,
) -> int:
    with SessionLocal() as session:
        row = AnalysisRun(
            user_id=user_id,
            dataset_id=dataset_id,
            dataset_revision=dataset_revision(dataset_path),
            procedure=procedure,
            title=(title or procedure)[:200],
            params=dict(params),
            payload=payload,
            duration_ms=int(duration_ms),
        )
        session.add(row)
        session.flush()
        # run_id нужен и внутри payload: по нему модель ссылается на расчёт,
        # а интерфейс открывает карточку.
        row.payload = {**payload, "run_id": int(row.id)}
        session.commit()
        return int(row.id)


def get_run(user_id: int, run_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(AnalysisRun, run_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Расчёт не найден")
        return {
            "run_id": row.id,
            "dataset_id": row.dataset_id,
            "dataset_revision": row.dataset_revision,
            "procedure": row.procedure,
            "title": row.title,
            "params": row.params,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "payload": row.payload,
        }


def list_runs(
    user_id: int, dataset_id: int | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        query = session.query(AnalysisRun).filter(AnalysisRun.user_id == user_id)
        if dataset_id is not None:
            query = query.filter(AnalysisRun.dataset_id == dataset_id)
        rows = query.order_by(AnalysisRun.id.desc()).limit(limit).all()
        return [
            {
                "run_id": row.id,
                "dataset_id": row.dataset_id,
                "procedure": row.procedure,
                "title": row.title,
                "dataset_revision": row.dataset_revision,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "duration_ms": row.duration_ms,
            }
            for row in rows
        ]


# ---------------------------------------------------------------- наборы


def list_datasets(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Наборы человека: id, имя, размеры, отпечаток файла."""
    with SessionLocal() as session:
        rows = (
            session.query(Dataset)
            .filter(Dataset.user_id == user_id)
            .order_by(Dataset.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "name": row.name,
                "n_cases": row.n_cases,
                "n_variables": row.n_variables,
                "revision": dataset_revision(row.path),
                "ai_full_access": bool(row.ai_full_access),
            }
            for row in rows
        ]


def dataset_row(user_id: int, dataset_id: int) -> Dataset:
    """Набор с проверкой владельца. Чужой выглядит как несуществующий."""
    with SessionLocal() as session:
        row = session.get(Dataset, dataset_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Набор не найден")
        session.expunge(row)
        return row


def set_ai_access(user_id: int, dataset_id: int, allow: bool) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(Dataset, dataset_id)
        if row is None or row.user_id != user_id:
            raise LookupError("Набор не найден")
        row.ai_full_access = bool(allow)
        session.commit()
        return {"dataset_id": row.id, "ai_full_access": bool(row.ai_full_access)}


__all__ = [
    "add_message",
    "add_tool_call",
    "conversation_detail",
    "count_user_messages_today",
    "create_conversation",
    "dataset_row",
    "delete_conversation",
    "finish_tool_call",
    "get_conversation",
    "get_run",
    "history",
    "list_conversations",
    "list_datasets",
    "list_runs",
    "save_run",
    "set_ai_access",
    "touch_conversation",
]

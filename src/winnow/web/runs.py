"""Сохранение и чтение выполненных расчётов.

Отдельный модуль, чтобы Stress Test и ИИ не зависели друг от друга. Каждая
функция открывает свою короткую сессию, как и хранилище ИИ.
"""

from __future__ import annotations

from typing import Any

from winnow.web.core import AnalysisRun, SessionLocal
from winnow.web.storage import dataset_revision


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
    """Сохраняет расчёт и возвращает run_id."""
    with SessionLocal() as session:
        row = AnalysisRun(
            user_id=user_id,
            dataset_id=dataset_id,
            dataset_revision=dataset_revision(dataset_path),
            procedure=procedure,
            title=(title or procedure)[:200],
            params=dict(params),
            payload=dict(payload),
            duration_ms=int(duration_ms),
        )
        session.add(row)
        session.flush()
        row.payload = {**payload, "run_id": int(row.id)}
        session.commit()
        return int(row.id)


def get_run(user_id: int, run_id: int) -> dict[str, Any]:
    """Возвращает расчёт пользователя или LookupError."""
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


__all__ = ["get_run", "save_run"]

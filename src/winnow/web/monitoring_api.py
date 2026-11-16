"""HTTP-слой сравнения волн исследования."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from winnow.analysis.monitoring import MonitoringConfig, compare_waves
from winnow.web.api import _load_stored, _owned
from winnow.web.core import User, get_db
from winnow.web.security import current_user

router = APIRouter(prefix="/api")


class MonitoringRequest(BaseModel):
    baseline_id: int
    current_id: int
    variables: list[str] | None = None
    alpha: float = Field(default=0.05, ge=0.001, le=0.2)


@router.post("/monitoring/compare")
def monitoring_compare(
    payload: MonitoringRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Сравнивает две волны; данные только читаются."""
    if payload.baseline_id == payload.current_id:
        raise HTTPException(status_code=422, detail="Выберите два разных набора")
    baseline_row = _owned(payload.baseline_id, user, db)
    current_row = _owned(payload.current_id, user, db)
    baseline = _load_stored(baseline_row)
    current = _load_stored(current_row)
    try:
        report = compare_waves(
            baseline,
            current,
            MonitoringConfig(
                variables=tuple(payload.variables) if payload.variables else None,
                alpha=payload.alpha,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = report.as_payload()
    # В файле набора могло сохраниться временное имя; для интерфейса важнее
    # название, которое человек дал загруженному файлу.
    result["baseline"]["name"] = baseline_row.name
    result["current"]["name"] = current_row.name
    return {
        "baseline_id": payload.baseline_id,
        "current_id": payload.current_id,
        "report": result,
    }

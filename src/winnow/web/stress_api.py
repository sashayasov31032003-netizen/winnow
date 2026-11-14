"""HTTP-слой Research Stress Test."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from winnow.analysis.stress import (
    CHECKS,
    DEFAULT_BOOTSTRAP,
    DEFAULT_SEED,
    MAX_BOOTSTRAP,
    StressConfig,
    run_stress_test,
)
from winnow.web.api import _load_stored, _owned
from winnow.web.core import User, get_db
from winnow.web.runs import get_run, save_run
from winnow.web.security import current_user

router = APIRouter(prefix="/api")


class StressRequest(BaseModel):
    """Параметры проверки устойчивости."""

    target: str
    predictors: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=lambda: ["auto"])
    auto: bool = True
    bootstrap: int = DEFAULT_BOOTSTRAP
    seed: int = DEFAULT_SEED
    confidence: float = 0.95
    alpha: float = 0.05
    add_controls: list[str] = Field(default_factory=list)


@router.post("/datasets/{dataset_id}/stress-test")
def stress_test(
    dataset_id: int,
    payload: StressRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Считает Stress Test, сохраняет прогон и возвращает отчёт."""
    if not payload.target.strip():
        raise HTTPException(status_code=422, detail="Выберите зависимую переменную")
    if len(payload.predictors) > 20:
        raise HTTPException(
            status_code=422, detail="Слишком много предикторов: максимум 20"
        )
    if len(payload.add_controls) > 20:
        raise HTTPException(
            status_code=422, detail="Слишком много контрольных переменных: максимум 20"
        )
    if payload.bootstrap < 0 or payload.bootstrap > MAX_BOOTSTRAP:
        raise HTTPException(
            status_code=422,
            detail=f"Bootstrap: от 0 до {MAX_BOOTSTRAP} повторов",
        )
    if payload.seed < 0:
        raise HTTPException(status_code=422, detail="Seed не может быть отрицательным")
    if payload.seed > 2_147_483_647:
        raise HTTPException(status_code=422, detail="Seed слишком большой")
    if not 0.5 <= payload.confidence <= 0.999:
        raise HTTPException(status_code=422, detail="Доверие должно быть от 0,5 до 0,999")
    if not 0.001 <= payload.alpha <= 0.2:
        raise HTTPException(status_code=422, detail="α должно быть от 0,001 до 0,2")

    checks = tuple(name for name in payload.checks if name in CHECKS)
    if not checks and not payload.auto:
        raise HTTPException(
            status_code=422,
            detail="Выберите хотя бы одну проверку или включите авто-режим",
        )
    config = StressConfig(
        target=payload.target.strip(),
        predictors=tuple(payload.predictors),
        checks=checks or CHECKS,
        bootstrap=payload.bootstrap,
        seed=payload.seed,
        confidence=payload.confidence,
        alpha=payload.alpha,
        add_controls=tuple(payload.add_controls),
        auto=payload.auto,
    )

    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    started = time.perf_counter()
    try:
        report = run_stress_test(dataset, config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - не отдаём traceback пользователю
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось выполнить Stress Test: {exc}",
        ) from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    run_id = save_run(
        user_id=user.id,
        dataset_id=dataset_id,
        dataset_path=row.path,
        procedure="stress_test",
        title=f"Stress Test: {config.target}",
        params=config.as_payload(),
        payload=report.as_payload(),
        duration_ms=duration_ms,
    )
    report.run_id = run_id
    return {
        "run_id": run_id,
        "report": report.as_payload(),
        "duration_ms": duration_ms,
    }


@router.get("/stress-tests/{run_id}")
def get_stress_test(
    run_id: int,
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Возвращает сохранённый Stress Test."""
    try:
        row = get_run(user.id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if row["procedure"] != "stress_test":
        raise HTTPException(status_code=404, detail="Stress Test не найден")
    return {"run": row}

"""HTTP-слой Research Stress Test."""

from __future__ import annotations

import pathlib
import tempfile
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from winnow.analysis.stress import (
    CHECKS,
    DEFAULT_BOOTSTRAP,
    DEFAULT_SEED,
    MAX_BOOTSTRAP,
    ChallengeConfig,
    StressConfig,
    run_stress_test,
)
from winnow.export import report_to_html, result_to_docx, result_to_xlsx
from winnow.stats.result import Result
from winnow.web.api import _load_stored, _owned
from winnow.web.core import User, get_db
from winnow.web.runs import get_run, list_runs, save_run
from winnow.web.security import current_user

router = APIRouter(prefix="/api")


class ChallengeRequest(BaseModel):
    """Исследовательская гипотеза для Research Challenge."""

    hypothesis: str
    focal: str
    direction: Literal["positive", "negative"] = "positive"
    controls: list[str] = Field(default_factory=list)


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
    challenge: ChallengeRequest | None = None
    exclude_rows: list[int] = Field(default_factory=list)


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
    challenge = None
    if payload.challenge is not None:
        if len(payload.challenge.controls) > 20:
            raise HTTPException(
                status_code=422,
                detail="Слишком много контрольных переменных гипотезы",
            )
        challenge = ChallengeConfig(
            hypothesis=payload.challenge.hypothesis,
            focal=payload.challenge.focal,
            direction=payload.challenge.direction,
            controls=tuple(payload.challenge.controls),
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
        challenge=challenge,
        exclude_rows=tuple(payload.exclude_rows),
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
    payload = report.as_payload()
    # Таблицы сохраняем рядом, чтобы экспорт не пересчитывал модель заново.
    payload["result"] = report.as_result().as_payload()
    run_id = save_run(
        user_id=user.id,
        dataset_id=dataset_id,
        dataset_path=row.path,
        procedure="stress_test",
        title=f"Stress Test: {config.target}",
        params=config.as_payload(),
        payload=payload,
        duration_ms=duration_ms,
    )
    report.run_id = run_id
    return {
        "run_id": run_id,
        "report": report.as_payload(),
        "duration_ms": duration_ms,
    }


@router.get("/datasets/{dataset_id}/stress-tests")
def list_stress_tests(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """История Stress Test для набора (новые сверху)."""
    _owned(dataset_id, user, db)
    return {"runs": list_runs(user.id, dataset_id, procedure="stress_test", limit=30)}


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


@router.get("/stress-tests/{run_id}/export")
def export_stress_test(
    run_id: int,
    format: str = "html",
    user: User = Depends(current_user),
) -> Response:
    """Экспорт сохранённого Stress Test в HTML, Word или Excel."""
    fmt = format.lower().strip()
    if fmt not in {"html", "docx", "xlsx"}:
        raise HTTPException(status_code=422, detail="Формат: html, docx или xlsx")
    try:
        row = get_run(user.id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if row["procedure"] != "stress_test":
        raise HTTPException(status_code=404, detail="Stress Test не найден")
    result_payload = (row.get("payload") or {}).get("result")
    if not result_payload:
        raise HTTPException(
            status_code=422,
            detail="В этом прогоне нет сохранённых таблиц; пересоберите Stress Test",
        )
    result = Result.from_payload(result_payload)
    filename = f"winnow-stress-test-{run_id}.{fmt}"
    if fmt == "html":
        content = report_to_html([result], title=row["title"] or "Research Stress Test").encode(
            "utf-8"
        )
        media = "text/html; charset=utf-8"
    else:
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / filename
            try:
                if fmt == "docx":
                    result_to_docx([result], target, title=row["title"] or "Research Stress Test")
                    media = (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    )
                else:
                    result_to_xlsx([result], target)
                    media = (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    )
            except ImportError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Для этого формата на сервере нет библиотеки экспорта",
                ) from exc
            content = target.read_bytes()
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

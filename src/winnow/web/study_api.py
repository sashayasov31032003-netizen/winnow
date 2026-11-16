"""Исследования, волны и тренды."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from winnow.analysis.trends import TrendWave, analyze_trends
from winnow.web.api import _load_stored, _owned
from winnow.web.core import Dataset, Study, StudyWave, User, get_db
from winnow.web.security import current_user

router = APIRouter(prefix="/api")


class StudyRequest(BaseModel):
    name: str
    description: str = ""


class WaveRequest(BaseModel):
    dataset_id: int
    label: str = ""
    year: int | None = Field(default=None, ge=1900, le=2200)


class TrendRequest(BaseModel):
    variables: list[str] | None = None
    alpha: float = Field(default=0.05, ge=0.001, le=0.2)


def _owned_study(study_id: int, user: User, db: Session) -> Study:
    study = db.get(Study, study_id)
    if study is None or study.user_id != user.id:
        raise HTTPException(status_code=404, detail="Исследование не найдено")
    return study


def _wave_payload(wave: StudyWave) -> dict[str, Any]:
    dataset = wave.dataset
    return {
        "id": wave.id,
        "dataset_id": wave.dataset_id,
        "label": wave.label,
        "year": wave.year,
        "position": wave.position,
        "dataset_name": dataset.name if dataset else "",
        "n_cases": dataset.n_cases if dataset else 0,
        "n_variables": dataset.n_variables if dataset else 0,
    }


@router.get("/studies")
def list_studies(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    studies = (
        db.query(Study)
        .filter(Study.user_id == user.id)
        .order_by(Study.created_at.desc(), Study.id.desc())
        .all()
    )
    return {
        "studies": [
            {
                "id": study.id,
                "name": study.name,
                "description": study.description,
                "waves": len(study.waves),
                "created_at": study.created_at.isoformat() if study.created_at else "",
            }
            for study in studies
        ]
    }


@router.post("/studies")
def create_study(
    payload: StudyRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название исследования обязательно")
    study = Study(
        user_id=user.id,
        name=name[:200],
        description=payload.description.strip()[:2000],
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return {"id": study.id, "name": study.name, "description": study.description, "waves": 0}


@router.get("/studies/{study_id}")
def get_study(
    study_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    study = _owned_study(study_id, user, db)
    return {
        "id": study.id,
        "name": study.name,
        "description": study.description,
        "created_at": study.created_at.isoformat() if study.created_at else "",
        "waves": [_wave_payload(wave) for wave in study.waves],
    }


@router.post("/studies/{study_id}/waves")
def add_wave(
    study_id: int,
    payload: WaveRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    study = _owned_study(study_id, user, db)
    dataset_row = _owned(payload.dataset_id, user, db)
    if any(wave.dataset_id == dataset_row.id for wave in study.waves):
        raise HTTPException(status_code=409, detail="Этот набор уже добавлен в исследование")
    position = max((wave.position for wave in study.waves), default=-1) + 1
    label = payload.label.strip() or dataset_row.name
    wave = StudyWave(
        study_id=study.id,
        dataset_id=dataset_row.id,
        label=label[:80],
        year=payload.year,
        position=position,
    )
    db.add(wave)
    db.commit()
    db.refresh(wave)
    return _wave_payload(wave)


@router.delete("/studies/{study_id}/waves/{wave_id}")
def remove_wave(
    study_id: int,
    wave_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    study = _owned_study(study_id, user, db)
    wave = next((item for item in study.waves if item.id == wave_id), None)
    if wave is None:
        raise HTTPException(status_code=404, detail="Волна не найдена")
    db.delete(wave)
    db.commit()
    return {"deleted": wave_id}


@router.delete("/studies/{study_id}")
def delete_study(
    study_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    study = _owned_study(study_id, user, db)
    db.delete(study)
    db.commit()
    return {"deleted": study_id}


@router.post("/studies/{study_id}/trends")
def study_trends(
    study_id: int,
    payload: TrendRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    study = _owned_study(study_id, user, db)
    if len(study.waves) < 2:
        raise HTTPException(status_code=422, detail="Для тренда нужны минимум две волны")
    waves: list[TrendWave] = []
    for wave in study.waves:
        try:
            dataset = _load_stored(wave.dataset)
        except HTTPException:
            continue
        waves.append(
            TrendWave(
                label=wave.label,
                dataset=dataset,
                year=wave.year,
                dataset_id=wave.dataset_id,
                position=wave.position,
            )
        )
    if len(waves) < 2:
        raise HTTPException(status_code=422, detail="Не удалось прочитать волны исследования")
    try:
        report = analyze_trends(
            waves,
            variables=tuple(payload.variables) if payload.variables else None,
            alpha=payload.alpha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "study_id": study.id,
        "study_name": study.name,
        "report": report.as_payload(),
    }

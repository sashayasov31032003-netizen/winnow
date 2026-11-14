"""HTTP-слой карты взаимосвязей переменных."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from winnow.analysis.relationships import (
    DEFAULT_MAX_VARIABLES,
    METHODS,
    RelationshipConfig,
    build_relationship_map,
)
from winnow.web.api import _load_stored, _owned
from winnow.web.core import User, get_db
from winnow.web.security import current_user
from winnow.web.storage import dataset_revision

router = APIRouter(prefix="/api")


class RelationshipsRequest(BaseModel):
    method: str = "auto"
    max_variables: int = Field(default=DEFAULT_MAX_VARIABLES, ge=2, le=120)


@router.post("/datasets/{dataset_id}/relationships")
def relationships(
    dataset_id: int,
    payload: RelationshipsRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Строит карту связей; данные только читаются."""
    if payload.method not in METHODS:
        raise HTTPException(
            status_code=422,
            detail="Метод: auto, pearson, spearman или kendall",
        )
    row = _owned(dataset_id, user, db)
    dataset = _load_stored(row)
    try:
        result = build_relationship_map(
            dataset,
            RelationshipConfig(
                method=payload.method,
                max_variables=payload.max_variables,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "dataset_revision": dataset_revision(row.path),
        **result.as_payload(),
    }

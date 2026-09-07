"""Checklist screen API (Phase 5 — see CLAUDE.md > Build Phases > Phase 5, Chunks 5.3/5.6).

HTTP only: parse, call app/services/checklist.py, wrap in the {"ok": ...} envelope. Exception
translation is central in app/main.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.checklist import (
    ChecklistItemResolve,
    ChecklistItemUpdate,
    ChecklistLoadResponse,
    ChecklistPushRequest,
)
from app.schemas.sessions import ChecklistItemRead
from app.services import checklist as checklist_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/checklist", tags=["checklist"])


def _item(row) -> dict:
    return ChecklistItemRead.model_validate(row).model_dump()


@router.get("/{session_id}")
def load_checklist(session_id: int, db: Session = Depends(get_db)) -> dict:
    items, anylist_ok, anylist_detail = checklist_service.load_checklist(db, session_id)
    body = ChecklistLoadResponse(
        session_id=session_id,
        anylist_ok=anylist_ok,
        anylist_detail=anylist_detail,
        items=[ChecklistItemRead.model_validate(r) for r in items],
        usuals=checklist_service.due_usuals(db),
    )
    return {"ok": True, "data": body.model_dump()}


@router.patch("/{session_id}/items/{item_id}")
def update_item(
    session_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    db: Session = Depends(get_db),
) -> dict:
    row = checklist_service.update_item(
        db, session_id, item_id, have_it=data.have_it, add_to_list=data.add_to_list
    )
    return {"ok": True, "data": _item(row)}


@router.post("/{session_id}/items/{item_id}/resolve")
def resolve_item(
    session_id: int,
    item_id: int,
    data: ChecklistItemResolve,
    db: Session = Depends(get_db),
) -> dict:
    row = checklist_service.resolve_item(
        db, session_id, item_id, total_quantity=data.total_quantity, total_unit=data.total_unit
    )
    return {"ok": True, "data": _item(row)}


@router.post("/{session_id}/push")
def push(
    session_id: int,
    data: ChecklistPushRequest | None = None,
    force: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    result = checklist_service.push_to_anylist(
        db, session_id, usual_ids=(data.usual_ids if data else None), force=force
    )
    return {"ok": True, "data": result}

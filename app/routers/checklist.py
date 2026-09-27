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
    ChecklistMergeRequest,
    ChecklistPushRequest,
)
from app.schemas.sessions import ChecklistItemRead
from app.services import checklist as checklist_service
from app.services import checklist_display
from app.services import progress_tracker
from app.services import usuals as usuals_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/checklist", tags=["checklist"])


def _item(db: Session, row) -> dict:
    return checklist_display.decorate(db, ChecklistItemRead.model_validate(row)).model_dump()


@router.get("/{session_id}")
def load_checklist(session_id: int, db: Session = Depends(get_db)) -> dict:
    items, anylist_ok, anylist_detail = checklist_service.load_checklist(db, session_id)
    body = ChecklistLoadResponse(
        session_id=session_id,
        anylist_ok=anylist_ok,
        anylist_detail=anylist_detail,
        items=[
            checklist_display.decorate(db, ChecklistItemRead.model_validate(r)) for r in items
        ],
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
    return {"ok": True, "data": _item(db, row)}


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
    return {"ok": True, "data": _item(db, row)}


@router.post("/{session_id}/merge")
def merge_items(
    session_id: int,
    data: ChecklistMergeRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Fold 2+ checklist lines into one (Fix 3 — CLAUDE.md > Deferred Decisions >
    checklist-time merge). Pre-push only (409 SESSION_ALREADY_PUSHED once pushed); a
    `remember=True` merge that names an already-aliased item surfaces 409
    DUPLICATE_INGREDIENT_ALIAS, same as Settings' own alias creation."""
    rows = checklist_service.merge_items(
        db,
        session_id,
        item_names=data.item_names,
        canonical_name=data.canonical_name,
        remember=data.remember,
        alias_qty=data.alias_qty,
        alias_unit=data.alias_unit,
        canonical_qty=data.canonical_qty,
        canonical_unit=data.canonical_unit,
    )
    return {"ok": True, "data": {"items": [_item(db, row) for row in rows]}}


@router.post("/usuals/{usual_id}/skip")
def skip_usual(usual_id: int, db: Session = Depends(get_db)) -> dict:
    """"I'm stocked, skip this time" (Phase 6 Chunk 6.3b, kickoff decision #8) — the same
    last_added_at stamp a push already applies via usuals_service.mark_added(), just not
    gated on an actual AnyList push. Not session-scoped: usual_items has no session_id, and
    the due-check that surfaces it on the checklist is global."""
    item = usuals_service.get_usual(db, usual_id)
    usuals_service.mark_added(db, [usual_id])
    db.refresh(item)
    return {"ok": True, "data": usuals_service.to_read(item)}


@router.post("/{session_id}/push")
def push(
    session_id: int,
    data: ChecklistPushRequest | None = None,
    force: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    result = checklist_service.push_to_anylist(
        db,
        session_id,
        usual_ids=(data.usual_ids if data else None),
        force=force,
        progress_token=(data.progress_token if data else None),
    )
    return {"ok": True, "data": result}


@router.get("/push/progress/{token}")
def push_progress(token: str) -> dict:
    """Polled by checklist-push.js while a push request is in flight (CLAUDE.md > UI/UX >
    Real progress indicators) — see app/services/progress_tracker.py. Same shape and 404
    behaviour as GET /recipes/capture/progress/{token}."""
    steps = progress_tracker.get(token)
    if steps is None:
        raise progress_tracker.ProgressTokenNotFoundError(token)
    return {"ok": True, "data": {"steps": steps}}

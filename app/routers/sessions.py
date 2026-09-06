"""Planning session API (Phase 4 — see CLAUDE.md > Build Phases > Phase 4).

HTTP only: parse, call app/services/sessions.py, wrap in the {"ok": ...} envelope
(CLAUDE.md > API Conventions). Exceptions are translated centrally in app/main.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.planning import SessionRecipe as SessionRecipeModel
from app.models.planning import PlanningSession as PlanningSessionModel
from app.schemas.sessions import (
    ChecklistItemRead,
    ConsolidateRequest,
    LeftoversSlotCreate,
    PlanningSessionCreate,
    PlanningSessionListItem,
    PlanningSessionRead,
    PlanningSessionUpdate,
    SessionRecipeCreate,
    SessionRecipeRead,
    SessionSlotUpdate,
    SlotOrderUpdate,
)
from app.services import sessions as sessions_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def _slot_read(slot: SessionRecipeModel) -> dict:
    data = SessionRecipeRead.model_validate(slot).model_dump(mode="json")
    data["recipe_name"] = slot.recipe.name if slot.recipe else None
    return data


def _session_read(session: PlanningSessionModel) -> dict:
    data = PlanningSessionRead.model_validate(session).model_dump(mode="json")
    data["recipes"] = [
        _slot_read(s) for s in sorted(session.recipes, key=lambda s: s.sort_order)
    ]
    return data


def _session_list_item(session: PlanningSessionModel) -> dict:
    data = PlanningSessionListItem.model_validate(session).model_dump(mode="json")
    data["slot_count"] = len(session.recipes)
    return data


# --- sessions ---------------------------------------------------------------


@router.post("", status_code=201)
def create_session(data: PlanningSessionCreate, db: Session = Depends(get_db)) -> dict:
    session = sessions_service.create_session(db, data)
    return {"ok": True, "data": _session_read(session)}


@router.get("")
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="Filter by 'active' | 'pushed' | 'archived'"),
    db: Session = Depends(get_db),
) -> dict:
    items, total = sessions_service.list_sessions(db, limit=limit, offset=offset, status=status)
    return {
        "ok": True,
        "data": {
            "items": [_session_list_item(s) for s in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    session = sessions_service.get_session(db, session_id)
    return {"ok": True, "data": _session_read(session)}


@router.patch("/{session_id}")
def update_session(
    session_id: int, data: PlanningSessionUpdate, db: Session = Depends(get_db)
) -> dict:
    session = sessions_service.update_session(db, session_id, data)
    return {"ok": True, "data": _session_read(session)}


@router.post("/{session_id}/archive")
def archive_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    session = sessions_service.archive_session(db, session_id)
    return {"ok": True, "data": _session_read(session)}


# --- slots ----------------------------------------------------------------


@router.post("/{session_id}/recipes", status_code=201)
def add_session_recipe(
    session_id: int, data: SessionRecipeCreate, db: Session = Depends(get_db)
) -> dict:
    slot = sessions_service.add_session_recipe(db, session_id, data)
    return {"ok": True, "data": _slot_read(slot)}


@router.post("/{session_id}/leftovers", status_code=201)
def add_leftovers_slot(
    session_id: int, data: LeftoversSlotCreate, db: Session = Depends(get_db)
) -> dict:
    slot = sessions_service.add_leftovers_slot(db, session_id, data)
    return {"ok": True, "data": _slot_read(slot)}


@router.patch("/{session_id}/slots/{slot_id}")
def update_slot(
    session_id: int, slot_id: int, data: SessionSlotUpdate, db: Session = Depends(get_db)
) -> dict:
    slot = sessions_service.update_slot(db, session_id, slot_id, data)
    return {"ok": True, "data": _slot_read(slot)}


@router.delete("/{session_id}/slots/{slot_id}")
def remove_slot(session_id: int, slot_id: int, db: Session = Depends(get_db)) -> dict:
    sessions_service.remove_slot(db, session_id, slot_id)
    return {"ok": True, "data": {"id": slot_id, "deleted": True}}


@router.put("/{session_id}/slots/order")
def reorder_slots(
    session_id: int, data: SlotOrderUpdate, db: Session = Depends(get_db)
) -> dict:
    slots = sessions_service.reorder_slots(db, session_id, data.ordered_ids)
    return {"ok": True, "data": [_slot_read(s) for s in slots]}


# --- consolidation (Chunk 4.6) --------------------------------------------


@router.post("/{session_id}/consolidate")
def consolidate_session(
    session_id: int,
    data: ConsolidateRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    items = sessions_service.consolidate_session(
        db, session_id, overrides=(data.overrides if data else None)
    )
    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "items": [
                ChecklistItemRead.model_validate(ci).model_dump(mode="json") for ci in items
            ],
        },
    }

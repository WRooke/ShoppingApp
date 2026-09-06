"""Planning-session business logic (Phase 4) — session CRUD and ordered slot
management. Plain Python / SQLAlchemy only, no `fastapi` import — see CLAUDE.md >
Code Architecture & Maintainability. Routers translate the exceptions below into
the {"ok": false, "error": ...} envelope centrally in app/main.py.

A slot (`session_recipes` row) is either a real recipe or a 'leftovers' marker.
Per CLAUDE.md > Code Architecture > file size discipline, the leftovers path is its
own function (`add_leftovers_slot`), not an `if slot_type == ...` branch inside the
recipe path.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.planning import PlanningSession, SessionRecipe
from app.schemas.sessions import (
    LeftoversSlotCreate,
    PlanningSessionCreate,
    PlanningSessionUpdate,
    SessionRecipeCreate,
    SessionSlotUpdate,
)
from app.services import recipes as recipes_service
from app.services.scaling import DEFAULT_TARGET_SERVINGS

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Planning session {session_id} not found")


class SessionSlotNotFoundError(Exception):
    def __init__(self, session_id: int, slot_id: int) -> None:
        self.session_id = session_id
        self.slot_id = slot_id
        super().__init__(f"Slot {slot_id} not found on session {session_id}")


class SlotOrderMismatchError(Exception):
    """The id list passed to reorder isn't exactly this session's current slot ids."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(
            f"Reorder for session {session_id} must list exactly its current slot ids"
        )


# --- sessions ---------------------------------------------------------------


def create_session(db: Session, data: PlanningSessionCreate) -> PlanningSession:
    session = PlanningSession(label=(data.label.strip() if data.label else None))
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("Planning session created: id=%s label=%r", session.id, session.label)
    return session


def get_session(db: Session, session_id: int) -> PlanningSession:
    session = db.get(PlanningSession, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    return session


def list_sessions(
    db: Session, *, limit: int = 50, offset: int = 0, status: str | None = None
) -> tuple[list[PlanningSession], int]:
    """(page of sessions, total). Newest first — this is a history-style list."""
    query = db.query(PlanningSession)
    if status:
        query = query.filter(PlanningSession.status == status)
    total = query.count()
    sessions = (
        query.order_by(PlanningSession.created_at.desc(), PlanningSession.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return sessions, total


def update_session(
    db: Session, session_id: int, data: PlanningSessionUpdate
) -> PlanningSession:
    session = get_session(db, session_id)
    changes = data.model_dump(exclude_unset=True)
    if "label" in changes:
        changes["label"] = changes["label"].strip() if changes["label"] else None
    for field, value in changes.items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    logger.info("Planning session updated: id=%s fields=%s", session_id, list(changes.keys()))
    return session


def archive_session(db: Session, session_id: int) -> PlanningSession:
    """Convenience for the common status change — sets status='archived'. There is no
    hard delete for sessions (CLAUDE.md > Build Phases > Phase 4 Chunk 4.4)."""
    session = get_session(db, session_id)
    session.status = "archived"
    db.commit()
    db.refresh(session)
    logger.info("Planning session archived: id=%s", session_id)
    return session


# --- slots ----------------------------------------------------------------


def _next_sort_order(session: PlanningSession) -> int:
    return max((s.sort_order for s in session.recipes), default=-1) + 1


def _get_slot(db: Session, session_id: int, slot_id: int) -> SessionRecipe:
    slot = db.get(SessionRecipe, slot_id)
    if slot is None or slot.session_id != session_id:
        raise SessionSlotNotFoundError(session_id, slot_id)
    return slot


def add_session_recipe(
    db: Session, session_id: int, data: SessionRecipeCreate
) -> SessionRecipe:
    """Add a real recipe slot. Validates the recipe exists (reusing
    recipes_service.RecipeNotFoundError -> 404). `scaled_servings` defaults to the
    household target when the caller doesn't set one."""
    session = get_session(db, session_id)
    recipes_service.get_recipe(db, data.recipe_id)  # raises RecipeNotFoundError

    slot = SessionRecipe(
        session_id=session.id,
        recipe_id=data.recipe_id,
        slot_type="recipe",
        day_of_week=data.day_of_week,
        scaled_servings=data.scaled_servings or DEFAULT_TARGET_SERVINGS,
        sort_order=data.sort_order if data.sort_order is not None else _next_sort_order(session),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session recipe slot added: session_id=%s slot_id=%s recipe_id=%s servings=%s",
        session_id,
        slot.id,
        slot.recipe_id,
        slot.scaled_servings,
    )
    return slot


def add_leftovers_slot(
    db: Session, session_id: int, data: LeftoversSlotCreate
) -> SessionRecipe:
    """Add a non-recipe 'leftovers' slot: no recipe_id, scaled_servings pinned to 0,
    contributes nothing to consolidation."""
    session = get_session(db, session_id)
    slot = SessionRecipe(
        session_id=session.id,
        recipe_id=None,
        slot_type="leftovers",
        day_of_week=data.day_of_week,
        scaled_servings=0,
        sort_order=data.sort_order if data.sort_order is not None else _next_sort_order(session),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session leftovers slot added: session_id=%s slot_id=%s day=%s",
        session_id,
        slot.id,
        slot.day_of_week,
    )
    return slot


def update_slot(
    db: Session, session_id: int, slot_id: int, data: SessionSlotUpdate
) -> SessionRecipe:
    slot = _get_slot(db, session_id, slot_id)
    changes = data.model_dump(exclude_unset=True)
    # scaled_servings is inert on a leftovers slot — keep it pinned at 0.
    if slot.slot_type == "leftovers":
        changes.pop("scaled_servings", None)
    for field, value in changes.items():
        if value is not None:
            setattr(slot, field, value)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session slot updated: session_id=%s slot_id=%s fields=%s",
        session_id,
        slot_id,
        list(changes.keys()),
    )
    return slot


def remove_slot(db: Session, session_id: int, slot_id: int) -> None:
    slot = _get_slot(db, session_id, slot_id)
    db.delete(slot)
    db.commit()
    logger.info("Session slot removed: session_id=%s slot_id=%s", session_id, slot_id)


def reorder_slots(db: Session, session_id: int, ordered_ids: list[int]) -> list[SessionRecipe]:
    """Set sort_order from position. `ordered_ids` must be exactly this session's current
    slot ids (any order) — a partial or foreign list is rejected rather than silently
    reordering a subset."""
    session = get_session(db, session_id)
    current = {s.id for s in session.recipes}
    if set(ordered_ids) != current or len(ordered_ids) != len(current):
        raise SlotOrderMismatchError(session_id)
    by_id = {s.id: s for s in session.recipes}
    for position, slot_id in enumerate(ordered_ids):
        by_id[slot_id].sort_order = position
    db.commit()
    logger.info("Session slots reordered: session_id=%s order=%s", session_id, ordered_ids)
    db.refresh(session)
    return sorted(session.recipes, key=lambda s: s.sort_order)

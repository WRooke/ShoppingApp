"""Checklist screen orchestrator (Phase 5) — load the consolidated checklist for a session,
match it against the current AnyList list to pre-tick, and (Chunk 5.6) push the result.

Plain Python / SQLAlchemy + the ``anylist_client`` interface; no ``fastapi`` import. Routers
(app/routers/checklist.py) translate the exceptions below into the ``{"ok": ...}`` envelope
centrally in app/main.py. See CLAUDE.md > Checklist Screen Logic and > AnyList Push Logic.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.catalog import Staple
from app.models.planning import SessionChecklistItem
from app.services import anylist_client
from app.services import sessions as sessions_service
from app.services.anylist_client import AnyListError

logger = logging.getLogger(__name__)


class ChecklistNotReadyError(Exception):
    """The session has no consolidated checklist yet — run POST /sessions/{id}/consolidate
    first (the Phase 4 review screen does this). 409 CHECKLIST_NOT_CONSOLIDATED."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} has no consolidated checklist yet")


class ChecklistItemNotFoundError(Exception):
    """404 CHECKLIST_ITEM_NOT_FOUND."""

    def __init__(self, session_id: int, item_id: int) -> None:
        self.session_id = session_id
        self.item_id = item_id
        super().__init__(f"Checklist item {item_id} not found on session {session_id}")


# --- name matching --------------------------------------------------------------------


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _singularise(s: str) -> str:
    """Very conservative de-pluralisation for fuzzy list matching (CLAUDE.md > Checklist
    Screen Logic: "fuzzy name match — normalised lowercase, strip plurals if needed").
    Handles the grocery-common cases (tomatoes, potatoes, boxes, dishes) and leaves anything
    ambiguous alone — a false negative just means the user ticks the item by hand, a false
    positive would pre-tick the wrong thing."""
    if len(s) > 4 and s.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return s[:-2]
    if len(s) > 3 and s.endswith("s") and not s.endswith("ss"):
        return s[:-1]
    return s


def _names_match(ingredient_name: str, anylist_name: str | None) -> bool:
    a, b = _norm(ingredient_name), _norm(anylist_name or "")
    if not a or not b:
        return False
    return a == b or _singularise(a) == _singularise(b)


def _find_match(
    ingredient_name: str, anylist_items: list[anylist_client.AnyListItem]
) -> anylist_client.AnyListItem | None:
    return next((i for i in anylist_items if _names_match(ingredient_name, i.name)), None)


# --- load -----------------------------------------------------------------------------


def load_checklist(db: Session, session_id: int) -> tuple[list[SessionChecklistItem], bool, str | None]:
    """(checklist items, anylist_ok, anylist_detail). Re-runs the AnyList match every call
    (the spec's "at checklist screen load" step). Upsert on the existing rows:
    `already_on_anylist` / `anylist_item_id` are recomputed *only when the AnyList fetch
    succeeds* (a transient failure must not wipe a good match); `have_it` is only ever
    *upgraded* from 'unknown' to 'yes' by a pre-tick, never downgraded; `is_staple` is
    re-confirmed every time. Never touches `add_to_list`."""
    session = sessions_service.get_session(db, session_id)  # raises SessionNotFoundError
    items = list(session.checklist_items)
    if not items:
        raise ChecklistNotReadyError(session_id)

    anylist_items: list[anylist_client.AnyListItem] = []
    anylist_ok, anylist_detail = True, None
    try:
        anylist_items = anylist_client.get_items()
    except anylist_client.AnyListDisabledError as exc:
        anylist_ok, anylist_detail = False, str(exc)
    except AnyListError as exc:
        anylist_ok, anylist_detail = False, str(exc)
        logger.warning("Checklist load: AnyList fetch failed, pre-tick skipped — %s", exc)

    staple_names = {s.name for s in db.query(Staple).all()}
    for ci in items:
        ci.is_staple = ci.ingredient_name in staple_names
        if not anylist_ok:
            continue  # keep whatever match state was there; don't wipe it on a transient fail
        match = _find_match(ci.ingredient_name, anylist_items)
        if match is not None:
            ci.already_on_anylist = True
            ci.anylist_item_id = match.identifier
            if ci.have_it == "unknown":
                ci.have_it = "yes"  # pre-tick; user can still untick
        else:
            ci.already_on_anylist = False
            ci.anylist_item_id = None

    db.commit()
    db.refresh(session)
    ordered = sorted(session.checklist_items, key=lambda c: c.ingredient_name)
    logger.info(
        "Checklist loaded: session_id=%s items=%d anylist_ok=%s on_list=%d",
        session_id,
        len(ordered),
        anylist_ok,
        sum(1 for c in ordered if c.already_on_anylist),
    )
    return ordered, anylist_ok, anylist_detail


def due_usuals(db: Session) -> list:
    """"The usuals" items that are currently due, as ChecklistUsualRead. Real implementation
    lands in Chunk 5.4 (services/usuals.py + the usual_items table); until then the checklist
    simply has no usuals group."""
    try:
        from app.services import usuals as usuals_service  # optional until Chunk 5.4
    except ImportError:
        return []
    return usuals_service.due_as_checklist_rows(db)


# --- per-item edits ------------------------------------------------------------------


def _get_item(db: Session, session_id: int, item_id: int) -> SessionChecklistItem:
    row = db.get(SessionChecklistItem, item_id)
    if row is None or row.session_id != session_id:
        raise ChecklistItemNotFoundError(session_id, item_id)
    return row


def update_item(
    db: Session,
    session_id: int,
    item_id: int,
    *,
    have_it: str | None = None,
    add_to_list: bool | None = None,
) -> SessionChecklistItem:
    row = _get_item(db, session_id, item_id)
    if have_it is not None:
        row.have_it = have_it
    if add_to_list is not None:
        row.add_to_list = add_to_list
    db.commit()
    db.refresh(row)
    logger.info(
        "Checklist item updated: session_id=%s item_id=%s have_it=%s add_to_list=%s",
        session_id, item_id, row.have_it, row.add_to_list,
    )
    return row


def resolve_item(
    db: Session, session_id: int, item_id: int, *, total_quantity: float, total_unit: str | None
) -> SessionChecklistItem:
    """Commit a single total for a Chunk 4.6 irreconcilable-units line and clear the flag."""
    row = _get_item(db, session_id, item_id)
    row.total_quantity = total_quantity
    row.total_unit = total_unit
    row.needs_review = False
    row.note = None
    db.commit()
    db.refresh(row)
    logger.info(
        "Checklist item resolved: session_id=%s item_id=%s -> %s %s",
        session_id, item_id, total_quantity, total_unit,
    )
    return row

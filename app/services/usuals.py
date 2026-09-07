""""The usuals" — recurring non-recipe household items on a day-based cadence (Phase 5
Chunk 5.4). CRUD + a due-date calculation. Plain Python / SQLAlchemy, no ``fastapi`` import.

An item is *due* when it has never been added (``last_added_at IS NULL``) or when
``last_added_at + cadence_days`` has passed. Due items surface as their own group on the
checklist (Chunk 5.5); pushing one to AnyList stamps ``last_added_at`` (Chunk 5.6). Seeded
empty — no pre-guessing, same call as the staples starter list.

See CLAUDE.md > Checklist Screen Logic > "The usuals" and > Data Model > usual_items.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.catalog import UsualItem
from app.schemas.usuals import UsualItemCreate, UsualItemUpdate

logger = logging.getLogger(__name__)


class UsualItemNotFoundError(Exception):
    def __init__(self, usual_id: int) -> None:
        self.usual_id = usual_id
        super().__init__(f"Usual item {usual_id} not found")


class DuplicateUsualItemNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"A usual item named {name!r} already exists")


def _normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def is_due(item: UsualItem, *, as_of: datetime | None = None) -> bool:
    if item.last_added_at is None:
        return True
    now = as_of or utcnow()
    return item.last_added_at + timedelta(days=item.cadence_days) <= now


def create_usual(db: Session, data: UsualItemCreate) -> UsualItem:
    item = UsualItem(
        name=_normalise_name(data.name),
        notes=data.notes,
        cadence_days=data.cadence_days,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateUsualItemNameError(item.name) from None
    db.refresh(item)
    logger.info("Usual item added: id=%s name=%r cadence_days=%s", item.id, item.name, item.cadence_days)
    return item


def get_usual(db: Session, usual_id: int) -> UsualItem:
    item = db.get(UsualItem, usual_id)
    if item is None:
        raise UsualItemNotFoundError(usual_id)
    return item


def list_usuals(db: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[UsualItem], int]:
    query = db.query(UsualItem)
    total = query.count()
    rows = query.order_by(UsualItem.name.asc()).offset(offset).limit(limit).all()
    return rows, total


def update_usual(db: Session, usual_id: int, data: UsualItemUpdate) -> UsualItem:
    item = get_usual(db, usual_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = _normalise_name(changes["name"])
    for field, value in changes.items():
        if value is not None:
            setattr(item, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateUsualItemNameError(changes.get("name", item.name)) from None
    db.refresh(item)
    logger.info("Usual item updated: id=%s fields=%s", usual_id, list(changes))
    return item


def delete_usual(db: Session, usual_id: int) -> None:
    item = get_usual(db, usual_id)
    db.delete(item)
    db.commit()
    logger.info("Usual item deleted: id=%s", usual_id)


def due_items(db: Session, *, as_of: datetime | None = None) -> list[UsualItem]:
    """Usual items currently due, name order. Kept as an in-Python filter (the list is tiny
    and `is_due` needs the per-row cadence) rather than a SQL date expression."""
    now = as_of or utcnow()
    return [
        i
        for i in db.query(UsualItem).order_by(UsualItem.name.asc()).all()
        if is_due(i, as_of=now)
    ]


def due_as_checklist_rows(db: Session) -> list:
    """Due items shaped as schemas.checklist.ChecklistUsualRead for the checklist load
    response (Chunk 5.3's `due_usuals` hook)."""
    from app.schemas.checklist import ChecklistUsualRead

    return [
        ChecklistUsualRead(
            id=i.id, name=i.name, notes=i.notes, cadence_days=i.cadence_days, add_to_list=False
        )
        for i in due_items(db)
    ]


def mark_added(db: Session, usual_ids: list[int], *, when: datetime | None = None) -> None:
    """Stamp ``last_added_at`` on the given usuals — called after they're pushed to AnyList
    (Chunk 5.6). Unknown ids are ignored (the push already happened; don't fail it)."""
    if not usual_ids:
        return
    stamp = when or utcnow()
    rows = db.query(UsualItem).filter(UsualItem.id.in_(usual_ids)).all()
    for row in rows:
        row.last_added_at = stamp
    db.commit()
    logger.info("Usual items marked added: ids=%s at=%s", [r.id for r in rows], stamp)


def to_read(item: UsualItem, *, as_of: datetime | None = None) -> dict:
    """UsualItemRead dict with `is_due` computed. Routers use this so `is_due` isn't a
    stored column."""
    from app.schemas.usuals import UsualItemRead

    data = UsualItemRead.model_validate(item).model_dump()
    data["is_due"] = is_due(item, as_of=as_of)
    return data

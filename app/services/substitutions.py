"""Remembered substitutions — the quick-pick library (Phase 3.9 M4).

Was a table of global auto-applying rules with an ``is_default``; that's gone (CLAUDE.md >
AI Provider Migration > The substitution merge). A ``remembered_substitutions`` row NEVER
applies a swap — it only pre-fills / top-ranks the suggestion in a per-recipe confirm UI
(capture review, recipe editor). The actual swap a recipe uses lives on
``recipe_ingredients.resolved_ingredient``.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.catalog import RememberedSubstitution
from app.schemas.substitutions import (
    RememberedSubstitutionCreate,
    RememberedSubstitutionUpdate,
)

logger = logging.getLogger(__name__)


class SubstitutionNotFoundError(Exception):
    def __init__(self, substitution_id: int) -> None:
        self.substitution_id = substitution_id
        super().__init__(f"Substitution {substitution_id} not found")


class DuplicateSubstitutionError(Exception):
    def __init__(self, original_name: str, substitute_name: str) -> None:
        self.original_name = original_name
        self.substitute_name = substitute_name
        super().__init__(
            f"Substitution {original_name!r} -> {substitute_name!r} already exists"
        )


class InvalidSubstitutionError(Exception):
    """e.g. substituting an ingredient with itself."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _normalise(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    trimmed = note.strip()
    return trimmed or None


def create_substitution(
    db: Session, data: RememberedSubstitutionCreate
) -> RememberedSubstitution:
    """Save one quick-pick swap. Names normalised lowercase; `last_used_at` set to now so a
    fresh entry sorts to the top of its group. No "default" concept (Phase 3.9 M4) — a row
    never applies itself. Raises InvalidSubstitutionError for a self-swap,
    DuplicateSubstitutionError for a repeated (original, substitute) pair."""
    original = _normalise(data.original_name)
    substitute = _normalise(data.substitute_name)
    if original == substitute:
        raise InvalidSubstitutionError("An ingredient can't be substituted with itself.")

    row = RememberedSubstitution(
        original_name=original,
        substitute_name=substitute,
        note=_clean_note(data.note),
        last_used_at=utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateSubstitutionError(original, substitute) from None
    db.refresh(row)
    logger.info("Remembered substitution added: id=%s %r -> %r", row.id, original, substitute)
    return row


def get_substitution(db: Session, substitution_id: int) -> RememberedSubstitution:
    row = db.get(RememberedSubstitution, substitution_id)
    if row is None:
        raise SubstitutionNotFoundError(substitution_id)
    return row


def list_substitutions(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[RememberedSubstitution], int]:
    """(page, total). Grouped-ish order: by original name, then most-recently-used, then
    substitute — so the Settings UI renders groups and the quick-pick order for free."""
    query = db.query(RememberedSubstitution)
    total = query.count()
    rows = (
        query.order_by(
            RememberedSubstitution.original_name.asc(),
            RememberedSubstitution.last_used_at.desc().nullslast(),
            RememberedSubstitution.substitute_name.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def quick_picks_for(db: Session, original_name: str) -> list[RememberedSubstitution]:
    """Remembered substitutes for one ingredient name, most-recently-used first — the
    quick-pick list shown in the per-recipe confirm UI."""
    return (
        db.query(RememberedSubstitution)
        .filter(RememberedSubstitution.original_name == _normalise(original_name))
        .order_by(RememberedSubstitution.last_used_at.desc().nullslast())
        .all()
    )


def update_substitution(
    db: Session, substitution_id: int, data: RememberedSubstitutionUpdate
) -> RememberedSubstitution:
    """Partial update of a saved swap — `substitute_name` and/or `note` only (`original_name`
    is immutable: delete + recreate). Re-normalises the substitute and re-checks the
    self-swap / duplicate-pair invariants."""
    row = get_substitution(db, substitution_id)
    changes = data.model_dump(exclude_unset=True)

    if "substitute_name" in changes and changes["substitute_name"] is not None:
        new_sub = _normalise(changes["substitute_name"])
        if new_sub == row.original_name:
            raise InvalidSubstitutionError("An ingredient can't be substituted with itself.")
        row.substitute_name = new_sub
    if "note" in changes:
        row.note = _clean_note(changes["note"])

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateSubstitutionError(row.original_name, row.substitute_name) from None
    db.refresh(row)
    logger.info("Remembered substitution updated: id=%s fields=%s", substitution_id, list(changes))
    return row


def delete_substitution(db: Session, substitution_id: int) -> None:
    """Removing a quick-pick never touches any recipe's resolved_ingredient or any past
    session (reversibility is recipe-level)."""
    row = get_substitution(db, substitution_id)
    db.delete(row)
    db.commit()
    logger.info("Remembered substitution deleted: id=%s", substitution_id)


def touch(db: Session, *, original_name: str, substitute_name: str) -> None:
    """Bump last_used_at on a matching remembered row (if any) so it floats to the top of
    the quick-picks. Called when a swap is confirmed on a recipe. Silent no-op if the pair
    isn't remembered."""
    row = (
        db.query(RememberedSubstitution)
        .filter(
            RememberedSubstitution.original_name == _normalise(original_name),
            RememberedSubstitution.substitute_name == _normalise(substitute_name),
        )
        .first()
    )
    if row is not None:
        row.last_used_at = utcnow()
        db.commit()

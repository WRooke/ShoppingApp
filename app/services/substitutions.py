"""Ingredient substitution rules — persistence + the read helper consolidation uses
(Phase 4, Chunk 4.5). Plain Python / SQLAlchemy only, no `fastapi` import — see
CLAUDE.md > Code Architecture & Maintainability. Exceptions below are translated to
the {"ok": false, ...} envelope centrally in app/main.py.

Design: CLAUDE.md > Ingredient Substitution. Key invariant — at most one `is_default`
row per `original_name` — is enforced here in the service (SQLite has no clean
partial-unique-index via the ORM), the same "enforce in services/" pattern as the
duplicate-name handling in services/settings.py. Setting a new default is a *reassign*
(the old one is demoted), never a 409.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import IngredientSubstitution
from app.schemas.substitutions import (
    IngredientSubstitutionCreate,
    IngredientSubstitutionUpdate,
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
    """Lowercase + collapse internal whitespace — matches recipe_ingredients.name so a
    rule lines up with consolidated ingredient names (CLAUDE.md > Ingredient Normalisation)."""
    return " ".join(name.strip().lower().split())


def _siblings(db: Session, original_name: str, *, exclude_id: int | None = None):
    q = db.query(IngredientSubstitution).filter(
        IngredientSubstitution.original_name == original_name
    )
    if exclude_id is not None:
        q = q.filter(IngredientSubstitution.id != exclude_id)
    return q.all()


def _clear_default(db: Session, original_name: str, *, exclude_id: int | None = None) -> None:
    for row in _siblings(db, original_name, exclude_id=exclude_id):
        if row.is_default:
            row.is_default = False


def create_substitution(
    db: Session, data: IngredientSubstitutionCreate
) -> IngredientSubstitution:
    original = _normalise(data.original_name)
    substitute = _normalise(data.substitute_name)
    if original == substitute:
        raise InvalidSubstitutionError("An ingredient can't be substituted with itself.")

    existing = _siblings(db, original)
    # First substitute for this ingredient always becomes the default; otherwise honour the
    # requested flag, demoting the current default if this one is taking that role.
    make_default = True if not existing else data.is_default
    if make_default:
        _clear_default(db, original)

    row = IngredientSubstitution(
        original_name=original, substitute_name=substitute, is_default=make_default
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateSubstitutionError(original, substitute) from None
    db.refresh(row)
    logger.info(
        "Substitution added: id=%s %r -> %r (default=%s)",
        row.id,
        original,
        substitute,
        row.is_default,
    )
    return row


def get_substitution(db: Session, substitution_id: int) -> IngredientSubstitution:
    row = db.get(IngredientSubstitution, substitution_id)
    if row is None:
        raise SubstitutionNotFoundError(substitution_id)
    return row


def list_substitutions(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[IngredientSubstitution], int]:
    """(page, total). Grouped-ish order: by original name, default first within a group,
    then substitute name — so the Settings UI can render groups without re-sorting."""
    query = db.query(IngredientSubstitution)
    total = query.count()
    rows = (
        query.order_by(
            IngredientSubstitution.original_name.asc(),
            IngredientSubstitution.is_default.desc(),
            IngredientSubstitution.substitute_name.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def update_substitution(
    db: Session, substitution_id: int, data: IngredientSubstitutionUpdate
) -> IngredientSubstitution:
    row = get_substitution(db, substitution_id)
    changes = data.model_dump(exclude_unset=True)

    if "substitute_name" in changes and changes["substitute_name"] is not None:
        new_sub = _normalise(changes["substitute_name"])
        if new_sub == row.original_name:
            raise InvalidSubstitutionError("An ingredient can't be substituted with itself.")
        row.substitute_name = new_sub

    if changes.get("is_default") is True:
        _clear_default(db, row.original_name, exclude_id=row.id)
        row.is_default = True
    elif changes.get("is_default") is False:
        # Allowed to leave a group with no default — nothing auto-applies for it then.
        row.is_default = False

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateSubstitutionError(row.original_name, row.substitute_name) from None
    db.refresh(row)
    logger.info("Substitution updated: id=%s fields=%s", substitution_id, list(changes.keys()))
    return row


def delete_substitution(db: Session, substitution_id: int) -> None:
    """Deleting the default does NOT auto-promote a sibling — deleting a rule means
    "stop auto-substituting"; remaining siblings stay as non-default quick-picks."""
    row = get_substitution(db, substitution_id)
    db.delete(row)
    db.commit()
    logger.info("Substitution deleted: id=%s", substitution_id)


def get_default_substitution_map(db: Session) -> dict[str, str]:
    """{original_name: substitute_name} for every default rule. Consumed by
    consolidation (Chunk 4.6) to resolve names before summing — see CLAUDE.md >
    Ingredient Substitution > Application."""
    return {
        row.original_name: row.substitute_name
        for row in db.query(IngredientSubstitution).filter(
            IngredientSubstitution.is_default.is_(True)
        )
    }

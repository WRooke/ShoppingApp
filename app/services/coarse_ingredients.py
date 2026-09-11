"""Coarse ingredients (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling > Layer D).

An ingredient in this table skips the normal sum -> normalise -> round consolidation
pipeline entirely — raised by "10g + 1 tbsp of parsley is probably just a bunch, I'm not out
shopping for parsley by the gram and tablespoon." Resolution (counting contributing recipe
slots, dividing by ``recipes_per_pack``) happens in
``services/session_consolidation.py > _coarse_items()``, which is the only caller of
``coarse_map()`` below — this module is CRUD only, no consolidation logic.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import CoarseIngredient
from app.schemas.coarse_ingredients import CoarseIngredientCreate, CoarseIngredientUpdate

logger = logging.getLogger(__name__)


class CoarseIngredientNotFoundError(Exception):
    def __init__(self, coarse_id: int) -> None:
        self.coarse_id = coarse_id
        super().__init__(f"Coarse ingredient {coarse_id} not found")


class DuplicateCoarseIngredientError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} is already a coarse ingredient")


def _normalise(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def create_coarse_ingredient(
    db: Session, data: CoarseIngredientCreate
) -> CoarseIngredient:
    row = CoarseIngredient(
        name=_normalise(data.name),
        purchase_label=_clean_text(data.purchase_label),
        recipes_per_pack=data.recipes_per_pack,
        notes=_clean_text(data.notes),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateCoarseIngredientError(row.name) from None
    db.refresh(row)
    logger.info(
        "Coarse ingredient added: id=%s name=%r purchase_label=%r recipes_per_pack=%s",
        row.id, row.name, row.purchase_label, row.recipes_per_pack,
    )
    return row


def get_coarse_ingredient(db: Session, coarse_id: int) -> CoarseIngredient:
    row = db.get(CoarseIngredient, coarse_id)
    if row is None:
        raise CoarseIngredientNotFoundError(coarse_id)
    return row


def list_coarse_ingredients(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[CoarseIngredient], int]:
    query = db.query(CoarseIngredient)
    total = query.count()
    rows = query.order_by(CoarseIngredient.name.asc()).offset(offset).limit(limit).all()
    return rows, total


def update_coarse_ingredient(
    db: Session, coarse_id: int, data: CoarseIngredientUpdate
) -> CoarseIngredient:
    row = get_coarse_ingredient(db, coarse_id)
    changes = data.model_dump(exclude_unset=True)
    if "purchase_label" in changes:
        row.purchase_label = _clean_text(changes["purchase_label"])
    if "recipes_per_pack" in changes and changes["recipes_per_pack"] is not None:
        row.recipes_per_pack = changes["recipes_per_pack"]
    if "notes" in changes:
        row.notes = _clean_text(changes["notes"])
    db.commit()
    db.refresh(row)
    logger.info("Coarse ingredient updated: id=%s fields=%s", coarse_id, list(changes))
    return row


def delete_coarse_ingredient(db: Session, coarse_id: int) -> None:
    row = get_coarse_ingredient(db, coarse_id)
    db.delete(row)
    db.commit()
    logger.info("Coarse ingredient deleted: id=%s", coarse_id)


def coarse_map(db: Session) -> dict[str, CoarseIngredient]:
    """The whole table as {name: CoarseIngredient} — loaded once per consolidate (same
    bulk-load pattern as ``ingredient_aliases.alias_map`` / ``unit_synonyms.synonym_map``)
    rather than a query per ingredient line."""
    return {row.name: row for row in db.query(CoarseIngredient).all()}

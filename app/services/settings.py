"""Settings business logic — CRUD for the `staples` and `product_units`
reference catalogue (see CLAUDE.md > Data Model > product_units / staples).
Plain Python / SQLAlchemy only, no `fastapi` import here — see CLAUDE.md >
Code Architecture & Maintainability. app/routers/settings.py calls these
functions and translates the exceptions below into the {"ok": false,
"error": ...} envelope.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import ProductUnit, Staple
from app.schemas.settings import (
    ProductUnitCreate,
    ProductUnitUpdate,
    StapleCreate,
    StapleUpdate,
)

logger = logging.getLogger(__name__)


class StapleNotFoundError(Exception):
    def __init__(self, staple_id: int) -> None:
        self.staple_id = staple_id
        super().__init__(f"Staple {staple_id} not found")


class DuplicateStapleNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Staple {name!r} already exists")


class ProductUnitNotFoundError(Exception):
    def __init__(self, product_unit_id: int) -> None:
        self.product_unit_id = product_unit_id
        super().__init__(f"Product unit {product_unit_id} not found")


class DuplicateProductUnitNameError(Exception):
    def __init__(self, ingredient_name: str) -> None:
        self.ingredient_name = ingredient_name
        super().__init__(f"Product unit for {ingredient_name!r} already exists")


def _normalise_name(name: str) -> str:
    """Lowercase + strip whitespace — matches recipe_ingredients.name so
    staples/product_units line up with consolidated ingredient names (see
    CLAUDE.md > Ingredient Normalisation)."""
    return name.strip().lower()


# --- staples ---------------------------------------------------------------


def create_staple(db: Session, data: StapleCreate) -> Staple:
    staple = Staple(name=_normalise_name(data.name), notes=data.notes)
    db.add(staple)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateStapleNameError(staple.name) from None
    db.refresh(staple)
    logger.info("Staple added: id=%s name=%r", staple.id, staple.name)
    return staple


def _get_staple(db: Session, staple_id: int) -> Staple:
    staple = db.get(Staple, staple_id)
    if staple is None:
        raise StapleNotFoundError(staple_id)
    return staple


def list_staples(db: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[Staple], int]:
    """Returns (page of staples, total count) for pagination (see CLAUDE.md >
    API Conventions). Ordered by name — this is a short reference list, not
    a feed, so alphabetical is what makes it scannable in Settings."""
    query = db.query(Staple)
    total = query.count()
    staples = query.order_by(Staple.name.asc()).offset(offset).limit(limit).all()
    return staples, total


def update_staple(db: Session, staple_id: int, data: StapleUpdate) -> Staple:
    staple = _get_staple(db, staple_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = _normalise_name(changes["name"])
    for field, value in changes.items():
        setattr(staple, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateStapleNameError(changes.get("name", staple.name)) from None
    db.refresh(staple)
    logger.info("Staple updated: id=%s fields=%s", staple_id, list(changes.keys()))
    return staple


def delete_staple(db: Session, staple_id: int) -> None:
    """Hard delete — staples has no soft-delete column in the data model
    (only recipes does)."""
    staple = _get_staple(db, staple_id)
    db.delete(staple)
    db.commit()
    logger.info("Staple deleted: id=%s", staple_id)


# --- product_units -----------------------------------------------------


def create_product_unit(db: Session, data: ProductUnitCreate) -> ProductUnit:
    product_unit = ProductUnit(
        ingredient_name=_normalise_name(data.ingredient_name),
        purchase_label=data.purchase_label.strip(),
        purchase_qty=data.purchase_qty,
        purchase_unit=data.purchase_unit,
        notes=data.notes,
        is_preseeded=False,
    )
    db.add(product_unit)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateProductUnitNameError(product_unit.ingredient_name) from None
    db.refresh(product_unit)
    logger.info(
        "Product unit added: id=%s ingredient_name=%r",
        product_unit.id,
        product_unit.ingredient_name,
    )
    return product_unit


def _get_product_unit(db: Session, product_unit_id: int) -> ProductUnit:
    product_unit = db.get(ProductUnit, product_unit_id)
    if product_unit is None:
        raise ProductUnitNotFoundError(product_unit_id)
    return product_unit


def list_product_units(
    db: Session, *, limit: int = 100, offset: int = 0
) -> tuple[list[ProductUnit], int]:
    """Returns (page of product units, total count) for pagination (see
    CLAUDE.md > API Conventions). Ordered by ingredient name for the same
    scannability reason as list_staples."""
    query = db.query(ProductUnit)
    total = query.count()
    product_units = query.order_by(ProductUnit.ingredient_name.asc()).offset(offset).limit(limit).all()
    return product_units, total


def update_product_unit(
    db: Session, product_unit_id: int, data: ProductUnitUpdate
) -> ProductUnit:
    product_unit = _get_product_unit(db, product_unit_id)
    changes = data.model_dump(exclude_unset=True)
    if "ingredient_name" in changes and changes["ingredient_name"] is not None:
        changes["ingredient_name"] = _normalise_name(changes["ingredient_name"])
    if "purchase_label" in changes and changes["purchase_label"] is not None:
        changes["purchase_label"] = changes["purchase_label"].strip()
    for field, value in changes.items():
        setattr(product_unit, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateProductUnitNameError(
            changes.get("ingredient_name", product_unit.ingredient_name)
        ) from None
    db.refresh(product_unit)
    logger.info(
        "Product unit updated: id=%s fields=%s", product_unit_id, list(changes.keys())
    )
    return product_unit


def delete_product_unit(db: Session, product_unit_id: int) -> None:
    """Hard delete — product_units has no soft-delete column, and deleting a
    (possibly is_preseeded) pack size the household doesn't actually buy is
    exactly what this Settings screen is for (see CLAUDE.md > Build Phases >
    Phase 2 > Chunk 2.5)."""
    product_unit = _get_product_unit(db, product_unit_id)
    db.delete(product_unit)
    db.commit()
    logger.info("Product unit deleted: id=%s", product_unit_id)

"""Pydantic request/response models for the Settings API — editing the
`staples` and `product_units` reference catalogue (see CLAUDE.md > Data
Model > product_units / staples). Kept separate from the SQLAlchemy ORM in
app/models/catalog.py on purpose, same reasoning as schemas/recipes.py — see
CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --- staples --------------------------------------------------------------


class StapleBase(BaseModel):
    name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    notes: str | None = None


class StapleCreate(StapleBase):
    pass


class StapleUpdate(BaseModel):
    """Partial update — every field optional, only fields actually sent are changed."""

    name: str | None = Field(None, min_length=1)
    notes: str | None = None


class StapleRead(StapleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class StapleListResponse(BaseModel):
    items: list[StapleRead]
    total: int
    limit: int
    offset: int


# --- product_units ----------------------------------------------------------


class ProductUnitBase(BaseModel):
    ingredient_name: str = Field(
        ..., min_length=1, description="Normalised lowercase; matches recipe_ingredients.name"
    )
    purchase_label: str = Field(..., min_length=1, description='e.g. "dozen", "500g pack"')
    purchase_qty: float = Field(..., gt=0)
    purchase_unit: str | None = None
    notes: str | None = None


class ProductUnitCreate(ProductUnitBase):
    """`is_preseeded` is never user-settable — every entry added here is a
    user addition, not a starter seed (see CLAUDE.md > Pre-seeded Product
    Units: "Mark all as is_preseeded = 1" refers only to seed_data.py's own
    startup seeding, not to rows a household member adds via Settings)."""


class ProductUnitUpdate(BaseModel):
    """Partial update — every field optional, only fields actually sent are changed."""

    ingredient_name: str | None = Field(None, min_length=1)
    purchase_label: str | None = Field(None, min_length=1)
    purchase_qty: float | None = Field(None, gt=0)
    purchase_unit: str | None = None
    notes: str | None = None


class ProductUnitRead(ProductUnitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_preseeded: bool
    created_at: datetime
    updated_at: datetime


class ProductUnitListResponse(BaseModel):
    items: list[ProductUnitRead]
    total: int
    limit: int
    offset: int

"""Pydantic models for ``coarse_ingredients`` — ingredients that skip quantity/unit math
entirely at consolidation (2026-09-12, see CLAUDE.md > Ingredient Unit Handling > Layer D and
> Data Model > coarse_ingredients).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CoarseIngredientCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    purchase_label: str | None = None
    recipes_per_pack: int = Field(3, ge=1)
    notes: str | None = None


class CoarseIngredientUpdate(BaseModel):
    """Partial update. `name` is not editable — delete and recreate, same convention as the
    other Settings-managed reference tables."""

    purchase_label: str | None = None
    recipes_per_pack: int | None = Field(None, ge=1)
    notes: str | None = None


class CoarseIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    purchase_label: str | None
    recipes_per_pack: int
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CoarseIngredientListResponse(BaseModel):
    items: list[CoarseIngredientRead]
    total: int
    limit: int
    offset: int

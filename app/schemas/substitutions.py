"""Pydantic models for ingredient substitution rules (Phase 4 — see CLAUDE.md >
Ingredient Substitution and > Data Model > ingredient_substitutions).

A rule says "treat `substitute_name` as interchangeable with `original_name` for
shopping". One `original_name` can have several substitutes; at most one is the
`is_default` (the one consolidation auto-applies silently). Kept separate from the
ORM in app/models/catalog.py per CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngredientSubstitutionBase(BaseModel):
    original_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    substitute_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    is_default: bool = False


class IngredientSubstitutionCreate(IngredientSubstitutionBase):
    """The first substitute recorded for an `original_name` always becomes the default,
    regardless of `is_default` here (see CLAUDE.md > Ingredient Substitution)."""


class IngredientSubstitutionUpdate(BaseModel):
    """Partial update. Setting `is_default=true` demotes the current default for that
    `original_name` (reassign, not a 409). `original_name` is not editable — delete and
    recreate instead."""

    substitute_name: str | None = Field(None, min_length=1)
    is_default: bool | None = None


class IngredientSubstitutionRead(IngredientSubstitutionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class IngredientSubstitutionListResponse(BaseModel):
    items: list[IngredientSubstitutionRead]
    total: int
    limit: int
    offset: int

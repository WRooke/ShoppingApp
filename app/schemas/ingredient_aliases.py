"""Pydantic models for ``ingredient_aliases`` — the "same shopping item" grouping (2026-09-10,
see CLAUDE.md > Ingredient Aliases and > Data Model > ingredient_aliases). Kept as its own
schema file, mirroring ``schemas/substitutions.py`` and ``schemas/usuals.py`` — a distinct
Settings-managed reference table gets its own schema module, even though all of them surface
on the same Settings page (CLAUDE.md > Code Architecture & Maintainability).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngredientAliasCreate(BaseModel):
    alias_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    canonical_name: str = Field(..., min_length=1, description="Normalised lowercase on save")


class IngredientAliasUpdate(BaseModel):
    """Partial update. `alias_name` is not editable — delete and recreate (same convention as
    RememberedSubstitutionUpdate's immutable `original_name`); re-grouping an existing alias
    under a different canonical name is the one supported change."""

    canonical_name: str | None = Field(None, min_length=1)


class IngredientAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias_name: str
    canonical_name: str
    created_at: datetime
    updated_at: datetime


class IngredientAliasListResponse(BaseModel):
    items: list[IngredientAliasRead]
    total: int
    limit: int
    offset: int

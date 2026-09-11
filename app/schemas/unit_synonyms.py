"""Pydantic models for ``unit_synonyms` — unit-spelling canonicalisation (2026-09-12, see
CLAUDE.md > Ingredient Unit Handling > Layer A and > Data Model > unit_synonyms). The plainer
sibling of ``schemas/ingredient_aliases.py`` — no equivalence pair needed, since a unit
doesn't need a quantity conversion to its own synonym.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UnitSynonymCreate(BaseModel):
    alias_unit: str = Field(..., min_length=1, description="Normalised lowercase on save")
    canonical_unit: str = Field(..., min_length=1, description="Normalised lowercase on save")


class UnitSynonymUpdate(BaseModel):
    """Partial update. `alias_unit` is not editable — delete and recreate (same convention as
    IngredientAliasUpdate's immutable `alias_name`); re-pointing to a different canonical
    unit is the one supported change."""

    canonical_unit: str | None = Field(None, min_length=1)


class UnitSynonymRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias_unit: str
    canonical_unit: str
    created_at: datetime
    updated_at: datetime


class UnitSynonymListResponse(BaseModel):
    items: list[UnitSynonymRead]
    total: int
    limit: int
    offset: int

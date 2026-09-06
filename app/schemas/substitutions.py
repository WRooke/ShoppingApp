"""Pydantic models for the remembered-substitutions quick-pick library (Phase 3.9 M4 — see
CLAUDE.md > Data Model > remembered_substitutions). Was ``IngredientSubstitution*`` with an
``is_default``; that concept is gone."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RememberedSubstitutionBase(BaseModel):
    original_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    substitute_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    note: str | None = None


class RememberedSubstitutionCreate(RememberedSubstitutionBase):
    pass


class RememberedSubstitutionUpdate(BaseModel):
    """Partial update. `original_name` is not editable — delete and recreate."""

    substitute_name: str | None = Field(None, min_length=1)
    note: str | None = None


class RememberedSubstitutionRead(RememberedSubstitutionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RememberedSubstitutionListResponse(BaseModel):
    items: list[RememberedSubstitutionRead]
    total: int
    limit: int
    offset: int

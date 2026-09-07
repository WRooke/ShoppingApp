"""Pydantic models for "the usuals" — recurring non-recipe household items (Phase 5
Chunk 5.4). Same CRUD shape as staples; adds ``cadence_days`` and the read-only
``last_added_at`` / ``is_due``. See CLAUDE.md > Data Model > usual_items.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UsualItemBase(BaseModel):
    name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    notes: str | None = None
    cadence_days: int = Field(..., ge=1, description="Buy roughly every N days")


class UsualItemCreate(UsualItemBase):
    pass


class UsualItemUpdate(BaseModel):
    """Partial update — every field optional."""

    name: str | None = Field(None, min_length=1)
    notes: str | None = None
    cadence_days: int | None = Field(None, ge=1)


class UsualItemRead(UsualItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_added_at: datetime | None
    is_due: bool = False  # set by the service (last_added_at IS NULL or cadence elapsed)
    created_at: datetime
    updated_at: datetime


class UsualItemListResponse(BaseModel):
    items: list[UsualItemRead]
    total: int
    limit: int
    offset: int

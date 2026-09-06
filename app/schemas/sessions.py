"""Pydantic request/response models for the planning-session API (Phase 4).

Kept separate from the SQLAlchemy ORM in app/models/planning.py on purpose — see
CLAUDE.md > Code Architecture & Maintainability. A session holds ordered *slots*
(`session_recipes` rows): each slot is either a real recipe or a non-recipe
"leftovers" marker that pulls nothing into consolidation (CLAUDE.md > Data Model >
session_recipes).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionStatus = Literal["active", "pushed", "archived"]
SlotType = Literal["recipe", "leftovers"]


# --- planning_sessions --------------------------------------------------------


class PlanningSessionCreate(BaseModel):
    label: str | None = Field(None, max_length=200)


class PlanningSessionUpdate(BaseModel):
    """Partial update — only label and status are user-editable here."""

    label: str | None = Field(None, max_length=200)
    status: SessionStatus | None = None


class SessionRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    slot_type: SlotType
    recipe_id: int | None
    recipe_name: str | None = None  # populated from the joined recipe, None for leftovers
    day_of_week: int | None
    scaled_servings: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


class PlanningSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str | None
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None
    recipes: list[SessionRecipeRead] = Field(default_factory=list)


class PlanningSessionListItem(BaseModel):
    """Lightweight shape for the sessions list — slot count, not the slots."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str | None
    status: SessionStatus
    slot_count: int = 0  # set by the router from len(session.recipes)
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None


class PlanningSessionListResponse(BaseModel):
    items: list[PlanningSessionListItem]
    total: int
    limit: int
    offset: int


# --- session slots ----------------------------------------------------------


class SessionRecipeCreate(BaseModel):
    """Add a real recipe to a session. `scaled_servings` defaults to the household
    target (DEFAULT_TARGET_SERVINGS) when omitted — see CLAUDE.md > Scaling Logic."""

    recipe_id: int
    day_of_week: int | None = Field(None, ge=1, le=7)
    scaled_servings: int | None = Field(None, ge=1)
    sort_order: int | None = None


class LeftoversSlotCreate(BaseModel):
    """Add a non-recipe "leftovers" slot. No recipe, no servings, contributes nothing
    to consolidation — it just occupies a day in the plan."""

    day_of_week: int | None = Field(None, ge=1, le=7)
    sort_order: int | None = None


class SessionSlotUpdate(BaseModel):
    """Partial update for any slot. `scaled_servings` is inert on a leftovers slot."""

    day_of_week: int | None = Field(None, ge=1, le=7)
    scaled_servings: int | None = Field(None, ge=1)
    sort_order: int | None = None


class SlotOrderUpdate(BaseModel):
    """Bulk reorder — the full list of this session's slot ids in the desired order."""

    ordered_ids: list[int] = Field(..., min_length=1)


# --- consolidation (Chunk 4.6) --------------------------------------------


class SessionOverride(BaseModel):
    """A one-off substitution that applies to THIS consolidate call only — nothing is
    written to `ingredient_substitutions`. Held client-side by the Chunk 4.7 UI and passed
    in here (CLAUDE.md > Ingredient Substitution > Creation: "No -> applies to this
    session's shopping list only")."""

    original_name: str = Field(..., min_length=1)
    substitute_name: str = Field(..., min_length=1)


class ConsolidateRequest(BaseModel):
    overrides: list[SessionOverride] = Field(default_factory=list)


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    ingredient_name: str
    total_quantity: float | None
    total_unit: str | None
    is_staple: bool
    already_on_anylist: bool
    have_it: str
    add_to_list: bool
    purchase_label: str | None
    purchase_qty: float | None
    display_qty: str | None
    needs_review: bool
    note: str | None
    created_at: datetime
    updated_at: datetime


class ConsolidateResponse(BaseModel):
    session_id: int
    items: list[ChecklistItemRead]

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


# SessionOverride / ConsolidateRequest removed 2026-09-30 (chunk 7.5) — the ad-hoc,
# session-only ingredient substitute used to be held client-side and sent in on every
# consolidate call; it's now a real `session_ingredient_merges` (kind='substitute') row,
# written via the checklist panel's own endpoint (routers/checklist.py) and read internally by
# `session_consolidation.py`, regardless of what triggered consolidation. See
# docs/checklist-and-shopping.md's "Review→Checklist merge — resolution" note.


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    ingredient_name: str
    # 2026-09-27 — natural-English display form of `ingredient_name` (which stays singular, the
    # stable matching key) for THIS line's own (total_quantity, total_unit) — see
    # services/checklist_display.py. NOT a session_checklist_items column: computed fresh by the
    # router on every read/response, same "ephemeral, derive don't store" precedent as
    # `recipe_breakdown` below. Falls back to `ingredient_name` itself when pydantic validates
    # straight off the ORM row (no such attribute there) — the router always overrides it via
    # `model_copy` before the response goes out; see routers/checklist.py.
    display_name: str = ""
    # 2026-09-27 — natural-English display form of `total_unit`, pluralised when it's a discrete
    # counting unit (clove, sprig, head, ...) and the quantity isn't 1 ("12 cloves"). A standard
    # measured unit (g, ml, tsp, ...) passes through unchanged regardless of quantity — see
    # services/checklist_display.py::display_unit. Same ephemeral/computed-fresh contract as
    # display_name above.
    display_unit: str | None = None
    total_quantity: float | None
    total_unit: str | None
    already_on_anylist: bool
    have_it: str
    add_to_list: bool
    purchase_label: str | None
    purchase_qty: float | None
    display_qty: str | None
    needs_review: bool
    note: str | None
    # 2026-09-13 code review — structured resolve-candidates for a needs_review line's "use X"
    # buttons; read from the SessionChecklistItem.review_options model property (parsed JSON),
    # always [] when the line isn't (or is no longer) needs_review. Replaces frontend regex-
    # parsing of `note` — see services/consolidation.py > ReviewOption.
    review_options: list["ReviewOptionRead"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    # 2026-09-11 — NOT a session_checklist_items column; always [] straight out of
    # model_validate(row) (pydantic falls back to the default when the ORM object has no such
    # attribute). The consolidate endpoint fills this in per-item afterwards via model_copy —
    # see routers/sessions.py and CLAUDE.md > "Which recipe is this ingredient from".
    recipe_breakdown: list["RecipeContribution"] = Field(default_factory=list)


class ReviewOptionRead(BaseModel):
    """One structured resolve-candidate — the API-facing twin of
    services.consolidation.ReviewOption. See ChecklistItemRead.review_options."""

    quantity: float
    unit: str | None = None
    # 2026-09-27 — natural-English display form of THIS option's own `unit` — see
    # ChecklistItemRead.display_unit and services/checklist_display.py::display_unit. The
    # ingredient's name is never repeated per-option (the checklist card already shows it once
    # as the row heading); only the amount needs to read naturally here, e.g. "12 cloves" rather
    # than "12 clove".
    display_unit: str | None = None


class RecipeContribution(BaseModel):
    """One recipe slot's contribution to a consolidated ingredient-review line — 2026-09-11,
    CLAUDE.md > "Which recipe is this ingredient from". Ephemeral: computed fresh on every
    consolidate pass, never persisted to session_checklist_items — not needed in shopping
    history. **2026-09-30 (chunk 7.3):** no longer review-screen-only — the now-deleted Review
    screen's breakdown toggle moved onto Checklist rows, which attaches this the same way
    routers/sessions.py's own consolidate endpoint always has (see routers/checklist.py's
    GET /{session_id})."""

    recipe_id: int | None
    recipe_label: str
    quantity: float
    unit: str | None
    is_no_scale: bool = False


class ConsolidateResponse(BaseModel):
    session_id: int
    items: list[ChecklistItemRead]


ChecklistItemRead.model_rebuild()  # resolves the forward refs to ReviewOptionRead/RecipeContribution, both defined below it

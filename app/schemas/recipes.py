"""Pydantic request/response models for the recipe library API.

Kept separate from the SQLAlchemy ORM in app/models/recipes.py on purpose — an
internal column can change without every response shape changing, and vice
versa. Routers import from here, never expose a raw ORM object as a response
body. See CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["url", "photo", "manual"]
Rating = Literal["up", "down"]


# --- recipe_ingredients ------------------------------------------------


class RecipeIngredientBase(BaseModel):
    name: str = Field(..., min_length=1, description="Ingredient name (normalised lowercase on save)")
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    sort_order: int = 0


class RecipeIngredientCreate(RecipeIngredientBase):
    pass


class RecipeIngredientUpdate(BaseModel):
    """Partial update — every field optional, only fields actually sent are changed."""

    name: str | None = Field(None, min_length=1)
    quantity: float | None = None
    unit: str | None = None
    preparation: str | None = None
    sort_order: int | None = None


class RecipeIngredientRead(RecipeIngredientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipe_id: int
    created_at: datetime
    updated_at: datetime


# --- recipes -------------------------------------------------------------


class RecipeBase(BaseModel):
    name: str = Field(..., min_length=1)
    source_type: SourceType = "manual"
    source_url: str | None = None
    source_image_path: str | None = None
    base_servings: int = Field(4, ge=1)
    # Source provenance (Chunk 3.7) — free text, orthogonal to source_type/source_url.
    # See CLAUDE.md > Data Model > recipes.
    source_book: str | None = Field(None, max_length=200)
    source_page: str | None = Field(None, max_length=50)
    notes: str | None = None
    cuisine: str | None = None
    protein: str | None = None


class RecipeCreate(RecipeBase):
    ingredients: list[RecipeIngredientCreate] = Field(default_factory=list)
    # Duplicate-recipe prevention (Phase 4) — when true, skip the possible-duplicate check
    # for this request only. The frontend sets it after the user clicks "Save anyway" on the
    # 409 warning panel. See CLAUDE.md > Duplicate Recipe Prevention.
    allow_duplicate: bool = False


class RecipeUpdate(BaseModel):
    """Partial update — every field optional. Ingredients are managed through the
    nested ingredient endpoints, not through this. `rating` is included here (not
    in RecipeBase) since it's user-editable from the detail view but never set at
    creation time — see CLAUDE.md > Data Model > recipes."""

    name: str | None = Field(None, min_length=1)
    source_type: SourceType | None = None
    source_url: str | None = None
    source_image_path: str | None = None
    base_servings: int | None = Field(None, ge=1)
    source_book: str | None = Field(None, max_length=200)
    source_page: str | None = Field(None, max_length=50)
    notes: str | None = None
    cuisine: str | None = None
    protein: str | None = None
    rating: Rating | None = None


class RecipeListItem(BaseModel):
    """Lightweight shape for the library browse list — no ingredients."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: SourceType
    base_servings: int
    cuisine: str | None
    protein: str | None
    rating: str | None
    times_made: int
    last_made_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RecipeRead(RecipeListItem):
    """Full detail shape, including ingredients."""

    source_url: str | None
    source_image_path: str | None
    source_book: str | None
    source_page: str | None
    notes: str | None
    ingredients: list[RecipeIngredientRead] = Field(default_factory=list)


class RecipeListResponse(BaseModel):
    items: list[RecipeListItem]
    total: int
    limit: int
    offset: int


# --- duplicate detection (Phase 4 — see CLAUDE.md > Duplicate Recipe Prevention) ----------

MatchedSignal = Literal["source_url", "name_exact", "book_page", "fuzzy_name"]


class DuplicateMatch(BaseModel):
    """One existing recipe that a save looked like. Carried in the 409
    POSSIBLE_DUPLICATE_RECIPE body's `detail`, and returned by the live
    GET /recipes/check-duplicate endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_summary: str | None = None  # URL, or "From {book}, p.{page}", or None
    matched_signal: MatchedSignal
    archived: bool


class CheckDuplicateResponse(BaseModel):
    matches: list[DuplicateMatch]

"""Pydantic request/response models for recipe capture (URL/photo extraction, then a
separate confirm-save step). See CLAUDE.md > Recipe Capture — AI Extraction and > Build
Phases > Phase 3.

Kept separate from schemas/recipes.py — capture's extraction result shape (raw, unsaved,
carries `suggested_section`/`original_text`) is deliberately not the same contract as a saved
recipe, per CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.recipes import SourceType


class CaptureUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)


class CapturedIngredient(BaseModel):
    """One extracted ingredient, not yet saved. `suggested_section` is AI-suggested and
    editable in the review UI (Chunk 3.4) — never trusted as final until confirm-save."""

    name: str
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    original_text: str = ""
    suggested_section: str | None = None


class CaptureResult(BaseModel):
    """What the two extraction endpoints return — enough for the review UI to render, and
    enough for the confirm-save step to reuse when the user hasn't edited anything."""

    source_type: SourceType
    source_url: str | None = None
    source_image_path: str | None = None
    cuisine: str | None = None
    protein: str | None = None
    ingredients: list[CapturedIngredient]


# --- confirm-save ------------------------------------------------------------


class CaptureIngredientConfirm(BaseModel):
    name: str = Field(..., min_length=1)
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    suggested_section: str | None = None


class CaptureConfirmRequest(BaseModel):
    """The reviewed-and-possibly-edited capture, ready to save as a real recipe. Mirrors
    RecipeCreate (schemas/recipes.py) plus per-ingredient `suggested_section`, which
    RecipeCreate has no use for outside of capture."""

    name: str = Field(..., min_length=1)
    source_type: SourceType
    source_url: str | None = None
    source_image_path: str | None = None
    base_servings: int = Field(4, ge=1)
    notes: str | None = None
    cuisine: str | None = None
    protein: str | None = None
    ingredients: list[CaptureIngredientConfirm] = Field(default_factory=list)

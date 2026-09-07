"""Pydantic request/response models for recipe capture (URL/photo extraction, then a
separate confirm-save step). See CLAUDE.md > Recipe Capture — AI Extraction and > Build
Phases > Phase 3.

Kept separate from schemas/recipes.py — capture's extraction result shape (raw, unsaved,
carries `suggested_section`/`original_text`) is deliberately not the same contract as a saved
recipe, per CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.recipes import SourceType, _validate_resolved_transform


class CaptureUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    # Duplicate prevention (Phase 4): on an exact source_url match the endpoint short-circuits
    # with a 409 before calling Claude. "Capture again anyway" re-submits with this true. See
    # CLAUDE.md > Duplicate Recipe Prevention > URL capture short-circuit.
    allow_duplicate: bool = False


class CapturedIngredient(BaseModel):
    """One extracted ingredient, not yet saved. `suggested_section` is AI-suggested and
    editable in the review UI (Chunk 3.4) — never trusted as final until confirm-save."""

    name: str
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    original_text: str = ""
    suggested_section: str | None = None


class SubstitutionFlagOut(BaseModel):
    """One AI-flagged substitution candidate for this recipe (Phase 3.9 M2). Enrichment —
    the review UI's per-ingredient confirm/decline is wired in M4."""

    original: str
    suggested_substitute: str
    note: str | None = None


class CaptureResult(BaseModel):
    """What the two extraction endpoints return — enough for the review UI to render, and
    enough for the confirm-save step to reuse when the user hasn't edited anything."""

    source_type: SourceType
    source_url: str | None = None
    source_image_path: str | None = None
    # AI-prefilled title/servings (Capture-Fixes-Staged.md issues 1 & 2, 2026-09-07) — both
    # editable on the review screen, never trusted as final until confirm-save, same as every
    # other extracted field. See CLAUDE.md > Recipe Capture > After extraction.
    title: str | None = None
    servings: int | None = None
    cuisine: str | None = None
    protein: str | None = None
    ingredients: list[CapturedIngredient]
    substitution_flags: list[SubstitutionFlagOut] = Field(default_factory=list)


# --- confirm-save ------------------------------------------------------------


class CaptureIngredientConfirm(BaseModel):
    name: str = Field(..., min_length=1)
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    suggested_section: str | None = None
    # Phase 3.9 M4 — a substitution the user confirmed on the review screen. None = no swap.
    resolved_ingredient: str | None = None
    substitution_note: str | None = None
    # Phase 3.9 M8 — the swap's absolute amount when it differs ("2 cob" -> "2 can"). Both-or-
    # neither; only valid with resolved_ingredient set.
    resolved_quantity: float | None = None
    resolved_unit: str | None = None

    @model_validator(mode="after")
    def _check_transform(self) -> "CaptureIngredientConfirm":
        _validate_resolved_transform(
            self.resolved_ingredient, self.resolved_quantity, self.resolved_unit
        )
        return self


class CaptureConfirmRequest(BaseModel):
    """The reviewed-and-possibly-edited capture, ready to save as a real recipe. Mirrors
    RecipeCreate (schemas/recipes.py) plus per-ingredient `suggested_section`, which
    RecipeCreate has no use for outside of capture."""

    name: str = Field(..., min_length=1)
    source_type: SourceType
    source_url: str | None = None
    source_image_path: str | None = None
    base_servings: int = Field(4, ge=1)
    # Source provenance (Chunk 3.7) — the review screen's optional cookbook name / page
    # inputs. See CLAUDE.md > Recipe Capture > Source provenance on the review screen.
    source_book: str | None = Field(None, max_length=200)
    source_page: str | None = Field(None, max_length=50)
    notes: str | None = None
    cuisine: str | None = None
    protein: str | None = None
    ingredients: list[CaptureIngredientConfirm] = Field(default_factory=list)
    # See RecipeCreate.allow_duplicate — "Save anyway" on the review screen's 409 panel.
    allow_duplicate: bool = False

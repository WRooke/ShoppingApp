"""Pydantic request/response models for the checklist screen (Phase 5).

The row shape is reused from ``schemas.sessions.ChecklistItemRead`` (same
``session_checklist_items`` table). This module only adds the checklist-specific
*request* bodies. See CLAUDE.md > Checklist Screen Logic and > Build Phases > Phase 5.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.equivalence import validate_alias_pair
from app.schemas.sessions import ChecklistItemRead

HaveIt = ("unknown", "yes", "no", "partial")  # 'partial' allowed by the column, never set (binary UX)


class ChecklistLoadResponse(BaseModel):
    session_id: int
    anylist_ok: bool  # whether the AnyList fetch during load succeeded
    anylist_detail: str | None = None  # e.g. "FAKE MODE", or the failure reason
    items: list[ChecklistItemRead]
    usuals: list["ChecklistUsualRead"] = Field(default_factory=list)


class ChecklistUsualRead(BaseModel):
    """A "the usuals" item that is currently due — offered as its own checklist group
    (Phase 5 Chunk 5.5). Not backed by session_checklist_items; carried alongside."""

    id: int
    name: str
    notes: str | None = None
    cadence_days: int
    add_to_list: bool = False  # client-held until push; not persisted here


class ChecklistItemUpdate(BaseModel):
    """Set one checklist line's user-controlled state. Both fields optional; send what changed."""

    have_it: str | None = Field(None, pattern="^(unknown|yes|no|partial)$")
    add_to_list: bool | None = None


class ChecklistPushRequest(BaseModel):
    """POST /checklist/{id}/push body — the due "usuals" the user ticked to include. The
    ingredient lines to push are read from the DB (add_to_list / have_it == 'no')."""

    usual_ids: list[int] = Field(default_factory=list)
    # Real-step push progress UI (2026-09-23, CLAUDE.md > UI/UX) — a client-generated token
    # polled via GET /checklist/push/progress/{token} while this request is in flight.
    progress_token: str | None = None


class ChecklistItemResolve(BaseModel):
    """Resolve a Chunk 4.6 irreconcilable-units line: commit a single total the user picked
    (one of the shown parts, or a manual figure). Clears ``needs_review``."""

    total_quantity: float = Field(..., gt=0)
    total_unit: str | None = None

    @model_validator(mode="after")
    def _clean(self) -> "ChecklistItemResolve":
        if self.total_unit is not None:
            self.total_unit = " ".join(self.total_unit.strip().lower().split()) or None
        return self


class ChecklistMergeRequest(BaseModel):
    """POST /checklist/{id}/merge body (Fix 3, F3.3 — CLAUDE.md > Deferred Decisions >
    checklist-time merge). `item_names` are already-consolidated `ingredient_name` values (the
    matching key, not display names); `canonical_name` must be one of them. `remember=True`
    writes a durable `ingredient_aliases` row (`source='user'`); `remember=False` writes a
    `session_ingredient_merges` row scoped to this session only. `pair` is the same optional
    equivalence-pair shape as an alias's own — see `schemas/equivalence.py`."""

    item_names: list[str] = Field(..., min_length=2)
    canonical_name: str = Field(..., min_length=1)
    remember: bool
    alias_qty: float | None = None
    alias_unit: str | None = None
    canonical_qty: float | None = None
    canonical_unit: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "ChecklistMergeRequest":
        if self.canonical_name not in self.item_names:
            raise ValueError("canonical_name must be one of item_names")
        validate_alias_pair(self.alias_qty, self.alias_unit, self.canonical_qty, self.canonical_unit)
        return self


ChecklistLoadResponse.model_rebuild()

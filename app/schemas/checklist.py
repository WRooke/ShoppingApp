"""Pydantic request/response models for the checklist screen (Phase 5).

The row shape is reused from ``schemas.sessions.ChecklistItemRead`` (same
``session_checklist_items`` table). This module only adds the checklist-specific
*request* bodies. See CLAUDE.md > Checklist Screen Logic and > Build Phases > Phase 5.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

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


ChecklistLoadResponse.model_rebuild()

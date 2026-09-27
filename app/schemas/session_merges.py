"""Pydantic models for ``session_ingredient_merges`` (Fix 3, F3.1 — see CLAUDE.md >
Deferred Decisions > checklist-time merge and > Data Model > session_ingredient_merges).

A session-scoped, ephemeral counterpart to ``ingredient_aliases``: "fold these two checklist
items into one, for this session only" (``remember=False`` at the router) vs. a durable
household preference (``remember=True`` writes a real ``ingredient_aliases`` row instead — see
``services/checklist.py::merge_items()``). Kept as its own schema module, mirroring
``schemas/ingredient_aliases.py`` — a distinct table gets its own schema file, same convention
as every other reference table in this app.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.equivalence import validate_alias_pair


class EquivalencePair(BaseModel):
    """The optional "N unit ~= M unit" transform a merge may carry — same shape and same
    (looser) validation rule as an `ingredient_aliases` pair (see
    `schemas/equivalence.py::validate_alias_pair`), reused here rather than a substitution's
    stricter one: a session merge is conceptually an alias's pair applied for one session only,
    not a substitution."""

    alias_qty: float | None = None
    alias_unit: str | None = None
    canonical_qty: float | None = None
    canonical_unit: str | None = None

    @model_validator(mode="after")
    def _check_pair(self) -> "EquivalencePair":
        validate_alias_pair(self.alias_qty, self.alias_unit, self.canonical_qty, self.canonical_unit)
        return self


class SessionIngredientMergeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    member_name: str
    canonical_name: str
    alias_qty: float | None
    alias_unit: str | None
    canonical_qty: float | None
    canonical_unit: str | None
    created_at: datetime

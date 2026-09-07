"""Pydantic models for the remembered-substitutions quick-pick library (Phase 3.9 M4 — see
CLAUDE.md > Data Model > remembered_substitutions). Was ``IngredientSubstitution*`` with an
``is_default``; that concept is gone.

Phase 3.9 M8 adds an optional *quantity/unit equivalence pair* to each saved swap
(``original_qty original_unit ~= substitute_qty substitute_unit``) — a ratio the per-recipe
confirm UI uses to pre-fill ``recipe_ingredients.resolved_quantity`` / ``resolved_unit``. See
CLAUDE.md > AI Provider Migration > Ingredient Substitution Flagging > Quantity/unit transform.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


def validate_equivalence_pair(
    original_qty: float | None,
    original_unit: str | None,
    substitute_qty: float | None,
    substitute_unit: str | None,
) -> None:
    """Shared rule for the M8 equivalence pair, used by both a saved swap
    (``remembered_substitutions``) and a session-only override (``SessionOverride``):

      * ``original_qty``/``original_unit`` are both-or-neither; so are
        ``substitute_qty``/``substitute_unit``.
      * a half-ratio is useless — either all four are set or none are.
      * both quantities must be positive (``original_qty`` is a divisor).
    """
    def _has(qty: float | None, unit: str | None) -> bool:
        return qty is not None or (unit is not None and unit.strip() != "")

    orig = _has(original_qty, original_unit)
    sub = _has(substitute_qty, substitute_unit)
    if orig and (original_qty is None or original_unit is None or not original_unit.strip()):
        raise ValueError("original_qty and original_unit must be set together")
    if sub and (substitute_qty is None or substitute_unit is None or not substitute_unit.strip()):
        raise ValueError("substitute_qty and substitute_unit must be set together")
    if orig != sub:
        raise ValueError(
            "a quantity equivalence needs all of original_qty/original_unit/"
            "substitute_qty/substitute_unit, or none of them"
        )
    if orig:
        if original_qty <= 0:
            raise ValueError("original_qty must be greater than 0")
        if substitute_qty <= 0:
            raise ValueError("substitute_qty must be greater than 0")


class _EquivalencePairMixin(BaseModel):
    original_qty: float | None = None
    original_unit: str | None = None
    substitute_qty: float | None = None
    substitute_unit: str | None = None


class RememberedSubstitutionBase(_EquivalencePairMixin):
    original_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    substitute_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    note: str | None = None

    @model_validator(mode="after")
    def _check_pair(self) -> "RememberedSubstitutionBase":
        validate_equivalence_pair(
            self.original_qty, self.original_unit, self.substitute_qty, self.substitute_unit
        )
        return self


class RememberedSubstitutionCreate(RememberedSubstitutionBase):
    pass


class RememberedSubstitutionUpdate(_EquivalencePairMixin):
    """Partial update. `original_name` is not editable — delete and recreate. Sending any of
    the four equivalence-pair fields replaces the whole pair, so the same all-or-none rule
    applies."""

    substitute_name: str | None = Field(None, min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _check_pair(self) -> "RememberedSubstitutionUpdate":
        sent = self.model_fields_set
        if sent & {"original_qty", "original_unit", "substitute_qty", "substitute_unit"}:
            validate_equivalence_pair(
                self.original_qty,
                self.original_unit,
                self.substitute_qty,
                self.substitute_unit,
            )
        return self


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

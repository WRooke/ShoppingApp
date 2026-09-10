"""Pydantic models for ``ingredient_aliases`` — the "same shopping item" grouping (2026-09-10,
see CLAUDE.md > Ingredient Aliases and > Data Model > ingredient_aliases). Kept as its own
schema file, mirroring ``schemas/substitutions.py`` and ``schemas/usuals.py`` — a distinct
Settings-managed reference table gets its own schema module, even though all of them surface
on the same Settings page (CLAUDE.md > Code Architecture & Maintainability).

2026-09-10 (lemon/lime juice -> whole fruit): an alias can optionally carry a quantity/unit
equivalence pair, the same *shape* as ``remembered_substitutions``' M8 pair but with its own,
slightly looser validator — see ``_validate_alias_pair`` for why it's not just
``schemas.substitutions.validate_equivalence_pair`` reused verbatim.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _validate_alias_pair(
    alias_qty: float | None,
    alias_unit: str | None,
    canonical_qty: float | None,
    canonical_unit: str | None,
) -> None:
    """Both-or-neither on the two quantities; both positive when set. Units are NOT required
    the way ``schemas.substitutions.validate_equivalence_pair`` requires them, on either
    side — a substitution's substitute is always some purchasable product with a real unit,
    but an alias's canonical target is very often a bare discrete count ("1 lemon", no unit,
    same as ``recipe_ingredients.unit`` being NULL for unitless produce). Keeping this
    genuinely symmetric (rather than requiring a unit on the alias side only) also covers a
    unitless alias name, should one ever come up."""
    alias_has = alias_qty is not None
    canonical_has = canonical_qty is not None
    if alias_has != canonical_has:
        raise ValueError(
            "a quantity equivalence needs both alias_qty and canonical_qty, or neither"
        )
    if alias_has:
        if alias_qty <= 0:
            raise ValueError("alias_qty must be greater than 0")
        if canonical_qty <= 0:
            raise ValueError("canonical_qty must be greater than 0")


class _EquivalencePairMixin(BaseModel):
    alias_qty: float | None = None
    alias_unit: str | None = None
    canonical_qty: float | None = None
    canonical_unit: str | None = None


class IngredientAliasCreate(_EquivalencePairMixin):
    alias_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    canonical_name: str = Field(..., min_length=1, description="Normalised lowercase on save")
    note: str | None = None

    @model_validator(mode="after")
    def _check_pair(self) -> "IngredientAliasCreate":
        _validate_alias_pair(
            self.alias_qty, self.alias_unit, self.canonical_qty, self.canonical_unit
        )
        return self


class IngredientAliasUpdate(_EquivalencePairMixin):
    """Partial update. `alias_name` is not editable — delete and recreate (same convention as
    RememberedSubstitutionUpdate's immutable `original_name`); re-grouping an existing alias
    under a different canonical name, or changing/clearing its equivalence pair, are the
    supported changes."""

    canonical_name: str | None = Field(None, min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _check_pair(self) -> "IngredientAliasUpdate":
        sent = self.model_fields_set
        if sent & {"alias_qty", "alias_unit", "canonical_qty", "canonical_unit"}:
            _validate_alias_pair(
                self.alias_qty, self.alias_unit, self.canonical_qty, self.canonical_unit
            )
        return self


class IngredientAliasRead(_EquivalencePairMixin):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias_name: str
    canonical_name: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class IngredientAliasListResponse(BaseModel):
    items: list[IngredientAliasRead]
    total: int
    limit: int
    offset: int

"""Pydantic models for ``ingredient_aliases`` — the "same shopping item" grouping (2026-09-10,
see CLAUDE.md > Ingredient Aliases and > Data Model > ingredient_aliases). Kept as its own
schema file, mirroring ``schemas/substitutions.py`` and ``schemas/usuals.py`` — a distinct
Settings-managed reference table gets its own schema module, even though all of them surface
on the same Settings page (CLAUDE.md > Code Architecture & Maintainability).

2026-09-10 (lemon/lime juice -> whole fruit): an alias can optionally carry a quantity/unit
equivalence pair, the same *shape* as ``remembered_substitutions``' M8 pair but with its own,
slightly looser validator — see ``schemas/equivalence.py::validate_alias_pair`` for why it's
not just ``schemas.substitutions.validate_equivalence_pair`` reused verbatim. 2026-09-27
(Fix 3, F3.1): that validator moved to ``schemas/equivalence.py`` so
``schemas/session_merges.py`` could reuse the exact same rule without a third copy-paste.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.equivalence import validate_alias_pair as _validate_alias_pair


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
    # 2026-09-27 (Fix 2, F2.1) -- "system" (a universal English fact) or "user" (a household
    # preference; the default). No `source` field on IngredientAliasCreate -- a household can
    # never set this to "system" via the API, only a migration can. See
    # app/models/catalog.py > IngredientAlias.source.
    source: str
    created_at: datetime
    updated_at: datetime


class IngredientAliasListResponse(BaseModel):
    items: list[IngredientAliasRead]
    total: int
    limit: int
    offset: int

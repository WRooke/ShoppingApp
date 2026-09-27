"""Shared quantity/unit equivalence-pair validation (Fix 3, F3.1 — see CLAUDE.md >
Deferred Decisions > checklist-time merge).

Promoted from ``schemas/ingredient_aliases.py``'s private ``_validate_alias_pair`` so a second
mechanism with the exact same equivalence-pair shape (``session_ingredient_merges``, F3.1)
doesn't need a third copy-paste — the same "don't repeat the matching-key mistake a second
time" lesson this whole plan already learned once for ``text_normalize.py``, applied
pre-emptively here. ``schemas/sessions.py`` already establishes the precedent of one schema
module importing another's validator (``validate_equivalence_pair`` from
``schemas/substitutions.py``), so this follows existing convention rather than inventing a new
one.

Deliberately the *looser* of this app's two equivalence-pair rules (contrast
``schemas.substitutions.validate_equivalence_pair``, which requires a unit on the substitute
side): both an alias's canonical target and a session merge's canonical target are very often a
bare discrete count ("1 lemon", no unit — same as ``recipe_ingredients.unit`` being NULL for
unitless produce), whereas a substitution's substitute is always some purchasable product with
a real unit. A session merge is conceptually an alias's equivalence pair applied for one
session only, not a substitution — so it reuses this rule, not the stricter one.
"""

from __future__ import annotations


def validate_alias_pair(
    alias_qty: float | None,
    alias_unit: str | None,
    canonical_qty: float | None,
    canonical_unit: str | None,
) -> None:
    """Both-or-neither on the two quantities; both positive when set. Units are NOT required
    on either side (contrast ``schemas.substitutions.validate_equivalence_pair`` — see the
    module docstring for why the two mechanisms need different rules here)."""
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

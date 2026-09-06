"""Recipe quantity scaling — pure arithmetic. No DB, no network, no rounding.

One of the three highest bug-risk modules (see CLAUDE.md > Code Architecture &
Maintainability), so it is kept deliberately tiny and heavily unit-tested.

Per the 2026-09-06 Phase 4 kickoff grilling, ``scaling.py`` does exactly one thing:
multiply a quantity by a factor. It does **not** round and it does **not** convert
units. All rounding and unit normalisation happen once, downstream, in
``consolidation.py`` + ``purchase_units.py`` (see CLAUDE.md > Scaling Logic and >
Build Phases > Phase 4 > Chunk 4.6) — doing it here as well would round twice and
let per-recipe rounding drift compound across a session.

"pinch" / "to taste" style amounts are not real quantities and pass through
untouched (``scaled=False``) so the consolidated list can show them without a number.
"""

from __future__ import annotations

from dataclasses import dataclass

# Matched case-insensitively (with surrounding whitespace stripped) against the unit
# string. Deliberately short; extend if real recipes surface more (flagged tunable).
NO_SCALE_UNITS = frozenset(
    {"pinch", "to taste", "taste", "splash", "drizzle", "dash"}
)


@dataclass(frozen=True)
class ScaledQuantity:
    quantity: float
    unit: str | None
    scaled: bool  # False => passed through untouched (a no-scale "to taste" amount)


def scaling_factor(base_servings: int, target_servings: int) -> float:
    """target / base. Raises on a non-positive base (a recipe must serve someone)."""
    if base_servings <= 0:
        raise ValueError("base_servings must be positive")
    return target_servings / base_servings


def scale_quantity(quantity: float, unit: str | None, factor: float) -> ScaledQuantity:
    """quantity * factor, unit preserved verbatim. No rounding. "to taste"-style
    units pass straight through with scaled=False."""
    if unit is not None and unit.strip().lower() in NO_SCALE_UNITS:
        return ScaledQuantity(quantity=quantity, unit=unit, scaled=False)
    return ScaledQuantity(quantity=quantity * factor, unit=unit, scaled=True)

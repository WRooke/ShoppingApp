"""Pure arithmetic for the checklist's "I have some" amount (Chunk 6.7, user-feedback batch, polish batch 3, item D).

A row's ``total_quantity``/``total_unit`` always mean the FULL amount the plan's recipes need.
``have_quantity`` is what the household already has at home, in that same unit. What actually
needs buying is the difference. Keeping the two apart (instead of subtracting into
``total_quantity``) matters because consolidation recomputes the total on every load: a
subtraction baked into it would be applied again on each recompute.

Units must match (case/whitespace-insensitive) for a subtraction to mean anything; a mismatch
(e.g. "have 200 g" against a total in "cup") is ignored here and the full total is bought. See
docs/checklist-and-shopping.md > "I have some".
"""

from __future__ import annotations


def _unit_key(unit: str | None) -> str:
    return " ".join((unit or "").lower().split())


def units_match(total_unit: str | None, have_unit: str | None) -> bool:
    return _unit_key(total_unit) == _unit_key(have_unit)


def amount_to_buy(
    total_quantity: float | None,
    total_unit: str | None,
    have_quantity: float | None,
    have_unit: str | None,
) -> float | None:
    """Quantity still to buy, in ``total_unit``. ``None`` when the row has no numeric total.
    Never negative. The full total when nothing (usable) is already had."""
    if total_quantity is None:
        return None
    if have_quantity is None or have_quantity <= 0 or not units_match(total_unit, have_unit):
        return total_quantity
    return max(round(total_quantity - have_quantity, 4), 0.0)


def covers_everything(
    total_quantity: float | None,
    total_unit: str | None,
    have_quantity: float | None,
    have_unit: str | None,
) -> bool:
    """True when the amount already had is at least the full amount needed (same unit)."""
    if total_quantity is None or have_quantity is None or have_quantity <= 0:
        return False
    return units_match(total_unit, have_unit) and have_quantity >= total_quantity

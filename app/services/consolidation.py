"""Ingredient consolidation — pure. No DB, no network. One of the three highest
bug-risk modules (CLAUDE.md > Code Architecture & Maintainability), heavily unit-tested.

Takes per-recipe *already-scaled* ingredient lines (from scaling.py) plus the default
substitution map, and returns one consolidated item per resolved ingredient name. This
is where every rounding and unit-normalisation rule from the 2026-09-06 grilling lives —
see CLAUDE.md > Scaling Logic > Rounding & unit rules:

  * Australian volume conversions: tsp=5 ml, tbsp=20 ml, cup=250 ml; kg=1000 g, L=1000 ml.
    Volumes merge; mass never converts to volume (no density data).
  * Sum, then round the sum UPWARD to a clean step (ceil 25 for g/ml >=100, ceil 5 below,
    ceil to whole for counts and free-text units). A purely-cup ingredient is shown back
    in cups, 2-dp, un-clean-rounded (the earlier explicit call for cups).
  * mass + volume for one ingredient => irreconcilable: not merged, flagged, parts shown.
  * "to taste" style amounts (scaling.NO_SCALE_UNITS) => shown with no number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

_ML_PER = {"ml": 1.0, "l": 1000.0, "tsp": 5.0, "tbsp": 20.0, "cup": 250.0}
_G_PER = {"g": 1.0, "kg": 1000.0}


@dataclass(frozen=True)
class IngredientLine:
    """One recipe's contribution of one ingredient, already scaled by scaling.py."""

    name: str
    quantity: float
    unit: str | None
    is_no_scale: bool = False  # scaling.ScaledQuantity.scaled == False ("to taste")


@dataclass
class ConsolidatedItem:
    name: str  # resolved (post-substitution) name
    quantity: float | None  # rounded required amount in `unit`; None for to-taste / review
    unit: str | None  # 'g' | 'kg' | 'ml' | 'L' | 'cup' | a free-text unit | None (count)
    is_no_scale: bool = False  # pure "to taste" item
    also_to_taste: bool = False  # has a real quantity AND a "to taste" contribution
    needs_review: bool = False  # mass + volume mix — not merged
    review_parts: list[str] = field(default_factory=list)  # ["100 g", "200 ml"]


def _dimension(unit: str | None) -> str:
    if unit is None:
        return "count"
    u = unit.strip().lower()
    if u in _G_PER:
        return "mass"
    if u in _ML_PER:
        return "volume"
    return f"unit:{u}"  # free-text unit — its own bucket, treated as a discrete count


def _ceil_step(value: float, step: float) -> float:
    return math.ceil(value / step) * step if value > 0 else 0.0


def _round_mass_or_volume_g_ml(value: float) -> float:
    """Ceil to a clean step: nearest 25 at/above 100, nearest 5 below. Never rounds down."""
    if value <= 0:
        return 0.0
    return _ceil_step(value, 25.0) if value >= 100 else _ceil_step(value, 5.0)


def _fmt_qty(value: float) -> str:
    """Trim a float for display: whole numbers lose the '.0', else up to 2 dp."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _summarise_bucket(dimension: str, total: float) -> str:
    if dimension == "mass":
        return f"{_fmt_qty(total)} g" if total < 1000 else f"{_fmt_qty(total / 1000)} kg"
    if dimension == "volume":
        return f"{_fmt_qty(total)} ml" if total < 1000 else f"{_fmt_qty(total / 1000)} L"
    if dimension == "count":
        return _fmt_qty(total)
    return f"{_fmt_qty(total)} {dimension.split(':', 1)[1]}"


def _resolve_group(name: str, lines: list[IngredientLine]) -> ConsolidatedItem:
    real = [ln for ln in lines if not ln.is_no_scale]
    has_to_taste = any(ln.is_no_scale for ln in lines)

    if not real:
        return ConsolidatedItem(name=name, quantity=None, unit=None, is_no_scale=True)

    # Bucket the real contributions by dimension, summing into a common base per bucket.
    buckets: dict[str, float] = {}
    cup_only_volume = True  # track whether every volume contribution was originally 'cup'
    for ln in real:
        dim = _dimension(ln.unit)
        if dim == "mass":
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity * _G_PER[ln.unit.strip().lower()]
        elif dim == "volume":
            u = ln.unit.strip().lower()
            if u != "cup":
                cup_only_volume = False
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity * _ML_PER[u]
        else:  # count / free-text unit
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity

    if len(buckets) > 1:
        parts = [_summarise_bucket(dim, total) for dim, total in sorted(buckets.items())]
        return ConsolidatedItem(
            name=name,
            quantity=None,
            unit=None,
            needs_review=True,
            review_parts=parts,
            also_to_taste=has_to_taste,
        )

    (dim, total), = buckets.items()
    if dim == "mass":
        rounded = _round_mass_or_volume_g_ml(total)
        if rounded >= 1000:
            return ConsolidatedItem(name, round(rounded / 1000, 2), "kg", also_to_taste=has_to_taste)
        return ConsolidatedItem(name, rounded, "g", also_to_taste=has_to_taste)
    if dim == "volume":
        if cup_only_volume:
            # honour the explicit "don't clean-round cups" call — show back in cups, 2 dp
            return ConsolidatedItem(name, round(total / 250.0, 2), "cup", also_to_taste=has_to_taste)
        rounded = _round_mass_or_volume_g_ml(total)
        if rounded >= 1000:
            return ConsolidatedItem(name, round(rounded / 1000, 2), "L", also_to_taste=has_to_taste)
        return ConsolidatedItem(name, rounded, "ml", also_to_taste=has_to_taste)
    if dim == "count":
        return ConsolidatedItem(name, float(math.ceil(total)), None, also_to_taste=has_to_taste)
    # free-text unit -> discrete, ceil to whole, keep the unit label
    return ConsolidatedItem(
        name, float(math.ceil(total)), dim.split(":", 1)[1], also_to_taste=has_to_taste
    )


def _normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def consolidate(lines: list[IngredientLine]) -> list[ConsolidatedItem]:
    """Group by ingredient name and apply the rounding/unit rules. Result sorted by name.

    **Pure — no substitution logic** (Phase 3.9 M4/M8). Each ``IngredientLine`` arrives
    finished: the caller (``sessions.consolidate_session`` / ``_scaled_lines``) has already
    resolved ``recipe_ingredients.resolved_ingredient``, applied the M8 quantity/unit
    transform (``resolved_quantity`` / ``resolved_unit`` or a session-override equivalence
    pair), and scaled. A line that came back as ``6 can`` from a "corn cobs" -> "canned corn"
    swap just buckets here as a free-text-unit discrete count. See CLAUDE.md > Scaling Logic
    > Consolidation across recipes."""
    grouped: dict[str, list[IngredientLine]] = {}
    for ln in lines:
        grouped.setdefault(_normalise_name(ln.name), []).append(ln)

    return sorted(
        (_resolve_group(name, group) for name, group in grouped.items()),
        key=lambda item: item.name,
    )

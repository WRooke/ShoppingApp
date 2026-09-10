"""Ingredient consolidation — pure. No DB, no network. One of the three highest
bug-risk modules (CLAUDE.md > Code Architecture & Maintainability), heavily unit-tested.

Takes per-recipe *already-scaled* ingredient lines (from scaling.py) plus the default
substitution map, and returns one consolidated item per resolved ingredient name. This
is where every rounding and unit-normalisation rule from the 2026-09-06 grilling lives —
see CLAUDE.md > Scaling Logic > Rounding & unit rules:

  * Australian volume conversions: tsp=5 ml, tbsp=20 ml, cup=250 ml; kg=1000 g, L=1000 ml.
    Volumes merge; mass never converts to volume (no density data).
  * Sum, then round the sum UPWARD to a clean step (ceil 25 for g/ml >=100, ceil 5 below,
    ceil to whole for counts and free-text units).
  * Spoon/cup exception (2026-09-10): if every volume contribution for an ingredient is a
    spoon/cup measure (tsp/tbsp/cup) and NONE is a literal ml/L, it never converts to ml —
    a bulky/leafy ingredient measured only in spoons ("2 tbsp baby spinach") doesn't read
    naturally as a millilitre figure. Shown back in whichever of cup/tbsp/tsp was actually
    used (cup wins if present): cup is 2-dp trimmed, un-clean-rounded (a scaled cup value is
    usually <1, where clean-rounding would destroy it); tbsp/tsp ceils to the nearest 0.5.
    A literal ml/L contribution anywhere signals a genuine liquid, so ALL of that
    ingredient's volume (spoons included) then goes through normal ml/L clean-rounding.
  * mass + volume for one ingredient => irreconcilable: not merged, flagged, parts shown.
  * "to taste" style amounts (scaling.NO_SCALE_UNITS) => shown with no number.

2026-09-10 (Ingredient Aliases' lemon/lime-juice equivalence-pair transform) — a line whose
name/quantity/unit were changed by an alias conversion may carry its PRE-conversion form
(``source_qty``/``source_unit``/``source_name``) purely for display ("from 3 tbsp lemon
juice"). This module treats it as opaque: it just sums matching (source_name, source_unit)
pairs within a group into ``ConsolidatedItem.conversion_notes`` and plays no part in deciding
whether/how a conversion happened — that logic lives in
``services/session_consolidation.py``.

2026-09-11 (recipe review "which recipe is this from" breakdown) — a line may also carry
which recipe slot it came from (``recipe_id``/``recipe_label``). Every line's OWN
(``quantity``, ``unit``) — already its post-substitution/post-alias, already-scaled final
form — becomes one ``RecipeContribution`` in the group's ``ConsolidatedItem.recipe_breakdown``,
listed one-per-line (never merged, even when two slots share a recipe — see CLAUDE.md >
Ingredient Aliases' sibling section on this). Again purely opaque display metadata: this
module doesn't know what a "recipe" is, it just carries the label through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

_ML_PER = {"ml": 1.0, "l": 1000.0, "tsp": 5.0, "tbsp": 20.0, "cup": 250.0}
_G_PER = {"g": 1.0, "kg": 1000.0}
_SPOON_CUP_UNITS = {"tsp", "tbsp", "cup"}


@dataclass(frozen=True)
class IngredientLine:
    """One recipe's contribution of one ingredient, already scaled by scaling.py."""

    name: str
    quantity: float
    unit: str | None
    is_no_scale: bool = False  # scaling.ScaledQuantity.scaled == False ("to taste")
    # 2026-09-10 — Ingredient Aliases quantity/unit transform (e.g. "lemon juice" -> "lemon").
    # Set together when an alias conversion changed this line's amount+unit: the PRE-
    # conversion (already-scaled) quantity/unit/name, purely for the "from 3 tbsp lemon
    # juice" display note. None for a name-only alias, a substitution, or no alias at all.
    source_qty: float | None = None
    source_unit: str | None = None
    source_name: str | None = None
    # 2026-09-11 — which recipe slot this line came from, for the ingredient-review "which
    # recipe is this from" breakdown. recipe_label is a ready-to-display string (e.g.
    # "Bolognese" or "Bolognese (Mon)" when a day is set) built by the caller — this module
    # never touches slot/day concepts. None only for a line with no recipe context (shouldn't
    # happen in practice — every real IngredientLine originates from a recipe slot — but kept
    # optional rather than assumed, matching source_qty/unit/name's own optionality).
    recipe_id: int | None = None
    recipe_label: str | None = None


@dataclass(frozen=True)
class RecipeContribution:
    """One recipe slot's contribution to a consolidated line — CLAUDE.md > "Which recipe is
    this ingredient from"."""

    recipe_id: int | None
    recipe_label: str
    quantity: float
    unit: str | None
    is_no_scale: bool = False  # a "to taste" contribution — quantity/unit are meaningless


@dataclass
class ConsolidatedItem:
    name: str  # resolved (post-substitution) name
    quantity: float | None  # rounded required amount in `unit`; None for to-taste / review
    unit: str | None  # 'g' | 'kg' | 'ml' | 'L' | 'cup' | a free-text unit | None (count)
    is_no_scale: bool = False  # pure "to taste" item
    also_to_taste: bool = False  # has a real quantity AND a "to taste" contribution
    needs_review: bool = False  # mass + volume mix — not merged
    review_parts: list[str] = field(default_factory=list)  # ["100 g", "200 ml"]
    # 2026-09-10 — summed (source_name, source_unit) contributions from any lines an alias
    # transform changed, formatted for display, e.g. ["3 tbsp lemon juice"]. Empty when no
    # line in this group went through an alias quantity/unit conversion.
    conversion_notes: list[str] = field(default_factory=list)
    # 2026-09-11 — one entry per contributing line (never merged, even for two slots of the
    # same recipe — CLAUDE.md > "Which recipe is this ingredient from"), for the ingredient
    # review screen's expandable "which recipe needed this" breakdown.
    recipe_breakdown: list[RecipeContribution] = field(default_factory=list)


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


def _conversion_notes(lines: list[IngredientLine]) -> list[str]:
    """Sum matching (source_name, source_unit) pairs across every line in a group into
    display-ready fragments ("3 tbsp lemon juice") — see CLAUDE.md > Ingredient Aliases. Two
    recipes each contributing "2 tbsp lemon juice" (aliased to the same canonical "lemon")
    show as one combined "4 tbsp lemon juice", not two separate fragments."""
    totals: dict[tuple[str, str], float] = {}
    for ln in lines:
        if ln.source_name is None:
            continue
        key = (ln.source_name, (ln.source_unit or "").strip().lower())
        totals[key] = totals.get(key, 0.0) + (ln.source_qty or 0.0)
    return [
        f"{_fmt_qty(qty)} {unit} {src_name}".strip() if unit else f"{_fmt_qty(qty)} {src_name}"
        for (src_name, unit), qty in totals.items()
    ]


def _recipe_breakdown(lines: list[IngredientLine]) -> list[RecipeContribution]:
    """One entry per line that carries a recipe_label, in the order given — never merged
    (CLAUDE.md > "Which recipe is this ingredient from": two slots of the same recipe show as
    two separate rows, e.g. different serving sizes on different days)."""
    return [
        RecipeContribution(
            recipe_id=ln.recipe_id, recipe_label=ln.recipe_label,
            quantity=ln.quantity, unit=ln.unit, is_no_scale=ln.is_no_scale,
        )
        for ln in lines
        if ln.recipe_label is not None
    ]


def _resolve_group(name: str, lines: list[IngredientLine]) -> ConsolidatedItem:
    real = [ln for ln in lines if not ln.is_no_scale]
    has_to_taste = any(ln.is_no_scale for ln in lines)
    conversion_notes = _conversion_notes(lines)
    recipe_breakdown = _recipe_breakdown(lines)

    def _item(quantity: float | None, unit: str | None, **kwargs) -> ConsolidatedItem:
        return ConsolidatedItem(
            name=name, quantity=quantity, unit=unit, conversion_notes=conversion_notes,
            recipe_breakdown=recipe_breakdown, **kwargs
        )

    if not real:
        return _item(None, None, is_no_scale=True)

    # Bucket the real contributions by dimension, summing into a common base per bucket.
    buckets: dict[str, float] = {}
    # Track whether every volume contribution was a spoon/cup measure (never a literal ml/L)
    # — see the spoon/cup display branch below.
    spoon_cup_only = True
    cup_used = False
    tbsp_used = False
    for ln in real:
        dim = _dimension(ln.unit)
        if dim == "mass":
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity * _G_PER[ln.unit.strip().lower()]
        elif dim == "volume":
            u = ln.unit.strip().lower()
            if u not in _SPOON_CUP_UNITS:
                spoon_cup_only = False
            elif u == "cup":
                cup_used = True
            elif u == "tbsp":
                tbsp_used = True
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity * _ML_PER[u]
        else:  # count / free-text unit
            buckets[dim] = buckets.get(dim, 0.0) + ln.quantity

    if len(buckets) > 1:
        parts = [_summarise_bucket(dim, total) for dim, total in sorted(buckets.items())]
        return _item(None, None, needs_review=True, review_parts=parts, also_to_taste=has_to_taste)

    (dim, total), = buckets.items()
    if dim == "mass":
        rounded = _round_mass_or_volume_g_ml(total)
        if rounded >= 1000:
            return _item(round(rounded / 1000, 2), "kg", also_to_taste=has_to_taste)
        return _item(rounded, "g", also_to_taste=has_to_taste)
    if dim == "volume":
        if spoon_cup_only:
            if cup_used:
                # Honour the explicit "don't clean-round cups" call — show back in cups, 2 dp.
                # Extended (2026-09-10 hand-testing) from "every contribution was cup" to
                # "cup appears at all, and nothing was a literal ml/L" so a cup+tbsp mix of
                # the same ingredient still gets a sane display unit instead of falling
                # through to the ml branch below.
                return _item(round(total / 250.0, 2), "cup", also_to_taste=has_to_taste)
            # CLAUDE.md > Scaling Logic's "pure tbsp/tsp -> ceil to nearest 0.5" rule — long
            # unreachable because this function unconditionally converted every tbsp/tsp
            # contribution to ml. 2026-09-10 hand-testing: a bulky/leafy ingredient measured
            # only in spoons (e.g. "baby spinach") doesn't read naturally as an ml figure
            # ("175 ml baby spinach"). As long as nothing for this ingredient was a literal
            # ml/L (which would mean a genuine liquid, where ml math is the right call —
            # see the fall-through below), display in whichever of tbsp/tsp was actually
            # used, ceiled to the nearest 0.5 rather than converted to ml.
            unit = "tbsp" if tbsp_used else "tsp"
            return _item(_ceil_step(total / _ML_PER[unit], 0.5), unit, also_to_taste=has_to_taste)
        rounded = _round_mass_or_volume_g_ml(total)
        if rounded >= 1000:
            return _item(round(rounded / 1000, 2), "L", also_to_taste=has_to_taste)
        return _item(rounded, "ml", also_to_taste=has_to_taste)
    if dim == "count":
        return _item(float(math.ceil(total)), None, also_to_taste=has_to_taste)
    # free-text unit -> discrete, ceil to whole, keep the unit label
    return _item(float(math.ceil(total)), dim.split(":", 1)[1], also_to_taste=has_to_taste)


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

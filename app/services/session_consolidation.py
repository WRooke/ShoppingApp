"""Session consolidation orchestrator (Phase 4 Chunk 4.6) — split out of
``services/sessions.py`` at the Phase 3.9 M-review per CLAUDE.md > Code Architecture > File
size and scope discipline.

This is the DB plumbing around the *pure* ``services/consolidation.py`` +
``purchase_units.py``: it pulls a session's scaled ingredient lines out of the DB (resolving
per-recipe ``resolved_ingredient`` / the M8 quantity/unit transform, any session-only
override, — 2026-09-10 — the ``ingredient_aliases`` "same shopping item" map, and — 2026-09-12
— the ``unit_synonyms`` spelling map), runs them through consolidation, resolves pack sizes,
and upserts ``session_checklist_items`` without discarding per-line checklist state
(``have_it`` / ``add_to_list`` / ``already_on_anylist`` / ``anylist_item_id``). The
rounding/unit rules themselves live in ``consolidation.py``. See CLAUDE.md > Scaling Logic,
> Ingredient Aliases, > Ingredient Unit Handling, and > Build Phases > Phase 4 > Chunk 4.6.
"""

from __future__ import annotations

import json
import logging
import math

from sqlalchemy.orm import Session

from app.models.catalog import ProductUnit, Staple
from app.models.planning import PlanningSession, SessionChecklistItem
from app.schemas.sessions import SessionOverride
from app.services import (
    coarse_ingredients,
    consolidation,
    ingredient_aliases,
    purchase_units,
    scaling,
    session_pack_resolution,
    unit_synonyms,
)
from app.services.sessions import get_session

logger = logging.getLogger(__name__)

# 1=Monday..7=Sunday (CLAUDE.md > Data Model > session_recipes). Only used to disambiguate
# _recipe_label() below when the same recipe is slotted into a session more than once.
_DAY_ABBR = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _effective_source(ing) -> tuple[float, str | None]:
    """The (quantity, unit) to scale for one recipe ingredient. Normally the recipe's own
    values; but when an M8 swap changes the *amount* (`resolved_ingredient` set AND
    `resolved_quantity` not NULL) the swap's absolute amount is scaled instead — so it grows
    with servings like any other quantity. See CLAUDE.md > Scaling Logic > Consolidation
    across recipes > Substitution quantity/unit transform."""
    if ing.resolved_ingredient and ing.resolved_quantity is not None:
        return ing.resolved_quantity, ing.resolved_unit
    return ing.quantity, ing.unit


def _apply_session_override(
    name: str, qty: float, unit: str | None, scaled: bool, ov: SessionOverride
) -> tuple[str, float, str | None]:
    """Fold a session-only override into an already-scaled line. Always renames; also
    transforms the amount when the override carries an equivalence pair AND its
    `original_unit` matches this line's unit (case-insensitive) AND the line is a real
    scalable quantity (not "to taste"). Otherwise it's a name-only swap for this line.
    The pair math is `qty / original_qty * substitute_qty`; `original_qty` is schema-checked
    > 0 but guarded here too."""
    new_name = _norm(ov.substitute_name)
    if (
        scaled
        and ov.original_qty
        and ov.original_qty > 0
        and ov.substitute_qty is not None
        and _norm(ov.original_unit or "") == _norm(unit or "")
    ):
        return new_name, qty / ov.original_qty * ov.substitute_qty, ov.substitute_unit
    return new_name, qty, unit


def _apply_alias(
    name: str, qty: float, unit: str | None, scaled: bool,
    alias_map: dict[str, ingredient_aliases.AliasResolution],
) -> tuple[str, float, str | None, tuple[float, str | None, str] | None]:
    """Fold an ingredient_aliases resolution into an already-scaled line, as the FINAL
    normalisation step (after any substitution / session override). Always renames when a
    match exists; also transforms the amount when the alias carries an equivalence pair
    ("2 tbsp lemon juice ~= 1 lemon") AND its `alias_unit` matches this line's unit
    (case-insensitive) AND the line is a real scalable quantity (not "to taste") — same
    matching rule as `_apply_session_override`'s M8 transform, and the same reasoning: a unit
    mismatch means we can't trust the ratio, so fall back to a name-only rename instead of
    guessing. Returns (name, qty, unit, source) where `source` is
    `(pre_conversion_qty, pre_conversion_unit, pre_conversion_name)` when a transform applied
    (for the "from 3 tbsp lemon juice" display note — CLAUDE.md > Ingredient Aliases), else
    None."""
    alias = alias_map.get(_norm(name))
    if alias is None:
        return name, qty, unit, None
    if (
        scaled
        and alias.has_pair
        and _norm(alias.alias_unit or "") == _norm(unit or "")
    ):
        new_qty = qty / alias.alias_qty * alias.canonical_qty
        return alias.canonical_name, new_qty, alias.canonical_unit, (qty, unit, name)
    return alias.canonical_name, qty, unit, None


def _recipe_label(slot) -> str:
    """Display label for one recipe slot's contributions to the "which recipe is this
    ingredient from" breakdown (CLAUDE.md). Just the recipe name, unless a day is set — the
    day disambiguates when the SAME recipe is slotted into a session more than once (e.g.
    meal-prepped for two different nights); no other disambiguator is attempted (two
    same-recipe, same-day-unset slots show as identical labels — accepted, see the
    "duplicate recipes" note in that section)."""
    day = _DAY_ABBR.get(slot.day_of_week)
    return f"{slot.recipe.name} ({day})" if day else slot.recipe.name


def _coarse_items(
    lines: list[consolidation.IngredientLine],
    coarse_cfg: dict[str, coarse_ingredients.CoarseIngredient],
) -> tuple[list[consolidation.ConsolidatedItem], list[consolidation.IngredientLine]]:
    """Partition already-resolved lines into (coarse ConsolidatedItems, remaining normal
    lines) — CLAUDE.md > Ingredient Unit Handling > Layer D. A coarse ingredient's lines
    never reach the pure `consolidation.consolidate()` at all: instead of summing quantity,
    `packs_needed = ceil(number of contributing recipe SLOTS / recipes_per_pack)`, ignoring
    what quantity/unit each line actually carries (that's the whole point — precision is
    pointless for these). `recipe_breakdown` is still built normally via the same helper
    `consolidate()` uses, since it's independent of how the total is computed and is exactly
    the "why do I need this" transparency the breakdown feature exists for.

    2026-09-13 code review fix: "number of contributing recipe SLOTS" is counted via each
    line's `slot_id` (deduped with a set), not `len(group)` — a single recipe listing the same
    coarse ingredient across two separate `recipe_ingredients` rows (e.g. "parsley, chopped"
    + "parsley, to garnish") produces two IngredientLines for ONE slot, and `len(group)` used
    to count that as 2 slots, inflating `coarse_packs_needed`. `slot_id` is set on every real
    line and on `_apply_shared_extraction_adjustment`'s synthetic correction lines alike (see
    that function), so this also correctly stays at 1 slot in the narrower case where a coarse
    ingredient happens to also be a shared-extraction-adjustment target."""
    grouped: dict[str, list[consolidation.IngredientLine]] = {}
    normal: list[consolidation.IngredientLine] = []
    for ln in lines:
        cfg = coarse_cfg.get(_norm(ln.name))
        if cfg is None:
            normal.append(ln)
        else:
            grouped.setdefault(_norm(ln.name), []).append(ln)

    def _slot_count(group: list[consolidation.IngredientLine]) -> int:
        slot_ids = {ln.slot_id for ln in group if ln.slot_id is not None}
        # Fall back to a raw line count only for a line with no slot_id at all (shouldn't
        # happen in practice — every real line is stamped by _scaled_lines() — but a missing
        # slot_id is safer counted as its own contribution than silently dropped).
        return len(slot_ids) + sum(1 for ln in group if ln.slot_id is None)

    coarse_items = [
        consolidation.ConsolidatedItem(
            name=name,
            quantity=None,
            unit=None,
            recipe_breakdown=consolidation._recipe_breakdown(group),
            is_coarse=True,
            coarse_packs_needed=math.ceil(_slot_count(group) / coarse_cfg[name].recipes_per_pack),
            coarse_purchase_label=coarse_cfg[name].purchase_label,
        )
        for name, group in grouped.items()
    ]
    return coarse_items, normal


def _apply_shared_extraction_adjustment(
    slot_lines: list[consolidation.IngredientLine],
) -> list[consolidation.IngredientLine]:
    """Within ONE recipe slot, if 2+ *different* alias sources (e.g. "lemon juice" and
    "lemon zest", tracked via `source_name`) each carrying a quantity/unit transform resolved
    to the same canonical name, they're almost certainly different extractions from the same
    physical unit in one cooking act (zest it, then juice it) — buying enough for the larger
    demand covers the smaller one "for free". A plain rename alias (no `source_name`, e.g.
    the oil-variant case) is never affected: it's a different, genuinely-additive substance,
    unchanged. See CLAUDE.md > Ingredient Aliases > Shared-source combining for the full
    design and the deliberate, accepted trade-off this represents.

    Implementation: for each canonical name with 2+ distinct `source_name` groups among this
    slot's own lines, add ONE synthetic correction line — quantity `max(group sums) -
    sum(group sums)` (always <= 0), `recipe_id`/`recipe_label` left `None` (so it never
    appears in the "which recipe" breakdown — it's not a real recipe contribution) and
    `source_name` left `None` (so it's never picked up by the conversion-notes aggregation).
    `slot_id` IS carried through (unlike recipe_id/recipe_label) — it's not a "which recipe"
    display concern, it's what lets `_coarse_items()` correctly recognise this correction line
    as belonging to the same slot as the real lines it adjusts, rather than inflating a coarse
    ingredient's slot count if its canonical name ever happens to also be a shared-extraction
    target (CLAUDE.md > Ingredient Unit Handling > Layer D).
    Every real line this slot produced is returned completely untouched alongside it, so the
    breakdown and conversion notes keep showing the real, honest, per-source amounts; only
    the final summed total (computed later, in the pure `consolidation.consolidate()`, which
    needs no changes at all to make this work) comes out reduced to the max."""
    groups: dict[str, dict[str, float]] = {}  # canonical name -> {source_name: summed qty}
    unit_by_name: dict[str, str | None] = {}
    slot_id = slot_lines[0].slot_id if slot_lines else None
    for ln in slot_lines:
        if ln.source_name is None:
            continue
        by_source = groups.setdefault(ln.name, {})
        by_source[ln.source_name] = by_source.get(ln.source_name, 0.0) + ln.quantity
        unit_by_name[ln.name] = ln.unit

    adjustments = []
    for name, by_source in groups.items():
        if len(by_source) < 2:
            continue  # only one extraction type present -- nothing to combine
        total = sum(by_source.values())
        peak = max(by_source.values())
        adjustments.append(
            consolidation.IngredientLine(
                name=name, quantity=peak - total, unit=unit_by_name[name], slot_id=slot_id
            )
        )
    return slot_lines + adjustments


def _scaled_lines(
    session: PlanningSession,
    override_map: dict[str, SessionOverride],
    alias_map: dict[str, ingredient_aliases.AliasResolution],
    synonym_map: dict[str, str],
) -> list[consolidation.IngredientLine]:
    """Scaled ingredient lines with the *effective* name (and, for M8/aliases, amount/unit)
    already resolved: the ingredient's own unit is canonicalised (2026-09-12, CLAUDE.md >
    Ingredient Unit Handling > Layer A) BEFORE anything else runs, so a recipe spelling a unit
    differently ("tablespoons" vs "tbsp") doesn't cause a session override's or an alias's own
    configured unit to spuriously fail to match; then per-recipe `resolved_ingredient` /
    `resolved_quantity` (fallback `name` / `quantity`), then a session-only override keyed off
    that resolved name, then — 2026-09-10 — the ingredient_aliases "same shopping item" map
    (optionally with its own quantity/unit transform, e.g. "lemon juice" -> "lemon"), as a
    final normalisation pass applied to whatever name/amount resulted from the steps before it
    (CLAUDE.md > Ingredient Aliases > Where it applies). `consolidation.consolidate()` itself
    does no substitution, aliasing, or unit-spelling resolution (Phase 3.9 M4/M8; 2026-09-10;
    2026-09-12). Each line also carries which recipe slot it came from: `recipe_id`/
    `recipe_label` (2026-09-11, CLAUDE.md > "Which recipe is this ingredient from"), purely for
    display, and `slot_id` (2026-09-13), purely for `_coarse_items()`'s slot-counting — neither
    plays any part in the resolution above. Finally, each recipe slot's OWN lines get one more
    pass —
    `_apply_shared_extraction_adjustment()` (2026-09-12, CLAUDE.md > Ingredient Aliases >
    Shared-source combining) — collapsing 2+ different alias sources sharing a canonical name
    *within that one recipe* down to their max rather than their sum (e.g. lemon juice + lemon
    zest in one recipe -> one shared lemon, not two)."""
    lines: list[consolidation.IngredientLine] = []
    for slot in session.recipes:
        if slot.slot_type != "recipe" or slot.recipe is None:
            continue  # leftovers slots contribute nothing
        factor = scaling.scaling_factor(slot.recipe.base_servings, slot.scaled_servings)
        label = _recipe_label(slot)
        slot_lines: list[consolidation.IngredientLine] = []
        for ing in slot.recipe.ingredients:
            base = ing.resolved_ingredient or ing.name
            src_qty, src_unit = _effective_source(ing)
            src_unit = unit_synonyms.resolve_unit(src_unit, synonym_map)
            sq = scaling.scale_quantity(src_qty, src_unit, factor)
            name, qty, unit = base, sq.quantity, sq.unit
            ov = override_map.get(_norm(base))
            if ov is not None:
                name, qty, unit = _apply_session_override(
                    name, qty, unit, sq.scaled, ov
                )
            name, qty, unit, source = _apply_alias(name, qty, unit, sq.scaled, alias_map)
            slot_lines.append(
                consolidation.IngredientLine(
                    name=name, quantity=qty, unit=unit, is_no_scale=not sq.scaled,
                    source_qty=source[0] if source else None,
                    source_unit=source[1] if source else None,
                    source_name=source[2] if source else None,
                    recipe_id=slot.recipe_id, recipe_label=label, slot_id=slot.id,
                )
            )
        lines.extend(_apply_shared_extraction_adjustment(slot_lines))
    return lines


def consolidate_session(
    db: Session, session_id: int, *, overrides: list[SessionOverride] | None = None
) -> list[SessionChecklistItem]:
    """Rebuild the consolidated checklist for a session. Upsert, not wipe: computed
    fields are recomputed, new lines added, gone lines removed, but per-line state
    (have_it / add_to_list / already_on_anylist / anylist_item_id) is PRESERVED for
    lines that persist (CLAUDE.md > Scaling Logic > re-running consolidation).

    Thin wrapper kept at this exact name/signature for every existing caller (the checklist
    load/push path, and the bulk of the test suite) — see `consolidate_session_with_breakdown`
    below for the one caller (the ingredient-review endpoint) that also needs the pure
    `ConsolidatedItem`s themselves, e.g. for `recipe_breakdown` (CLAUDE.md > "Which recipe is
    this ingredient from")."""
    rows, _items = _consolidate_session_impl(db, session_id, overrides=overrides)
    return rows


def consolidate_session_with_breakdown(
    db: Session, session_id: int, *, overrides: list[SessionOverride] | None = None
) -> tuple[list[SessionChecklistItem], dict[str, list[consolidation.RecipeContribution]]]:
    """Same upsert as `consolidate_session`, plus a {ingredient_name: recipe_breakdown} map —
    computed for free alongside it (no second consolidation pass) since the upsert loop
    already iterates the pure `ConsolidatedItem`s that carry this. Not persisted anywhere
    (CLAUDE.md > "Which recipe is this ingredient from" — confirmed ephemeral, review-screen-
    only): recomputed fresh on every call, same as the rest of consolidation."""
    rows, items = _consolidate_session_impl(db, session_id, overrides=overrides)
    breakdown = {item.name: item.recipe_breakdown for item in items}
    return rows, breakdown


def _consolidate_session_impl(
    db: Session, session_id: int, *, overrides: list[SessionOverride] | None = None
) -> tuple[list[SessionChecklistItem], list[consolidation.ConsolidatedItem]]:
    session = get_session(db, session_id)

    # Session-only overrides — client-held, not written anywhere (Phase 3.9 M4/M8). Per-recipe
    # `resolved_ingredient` / `resolved_quantity` is applied inside _scaled_lines; there is no
    # global rule map. Keyed by normalised original name; the whole override (incl. any M8
    # equivalence pair) is carried through.
    override_map = {_norm(ov.original_name): ov for ov in (overrides or [])}
    all_lines = _scaled_lines(
        session, override_map, ingredient_aliases.alias_map(db), unit_synonyms.synonym_map(db)
    )
    # Ingredient Unit Handling Layer D (2026-09-12) — a coarse ingredient's lines never reach
    # the pure consolidate() below; they're grouped and resolved by _coarse_items() instead.
    coarse_items, normal_lines = _coarse_items(all_lines, coarse_ingredients.coarse_map(db))
    items = coarse_items + consolidation.consolidate(normal_lines)

    staple_names = {s.name for s in db.query(Staple).all()}
    existing = {ci.ingredient_name: ci for ci in session.checklist_items}

    for item in items:
        row = existing.pop(item.name, None)
        if row is None:
            row = SessionChecklistItem(session_id=session.id, ingredient_name=item.name)
            db.add(row)

        row.is_staple = item.name in staple_names

        # 2026-09-10 hand-testing ("doesn't remember amounts under review") — a needs_review
        # conflict the user manually resolved (checklist.resolve_item(), which sets
        # review_resolved_by_user) must not be clobbered by this recompute while the same
        # ingredient STILL conflicts; otherwise every re-consolidate (adding a recipe,
        # changing servings, re-opening the review screen) silently re-flagged and reset the
        # user's choice. Once the conflict is actually gone, fall through to the normal
        # recompute and clear the flag — a stale manual pick from an unrelated earlier
        # conflict must not be reused for a fresh single-dimension total.
        if row.review_resolved_by_user and item.needs_review:
            continue
        row.review_resolved_by_user = False

        # reset computed fields every run
        row.total_quantity = item.quantity
        row.total_unit = item.unit
        row.purchase_label = None
        row.purchase_qty = None
        row.display_qty = None
        row.needs_review = item.needs_review
        row.note = None
        row.review_options_json = None

        if item.is_coarse:
            # Ingredient Unit Handling Layer D (2026-09-12) — no quantity/unit math at all;
            # `_pack_options_for`/`purchase_units.resolve_packs()` (precision-driven pack-size
            # resolution) are skipped entirely, matching what "coarse" means opting out of.
            if item.coarse_purchase_label:
                row.display_qty = f"{item.coarse_packs_needed} × {item.coarse_purchase_label}"
                row.purchase_label = item.coarse_purchase_label
                row.purchase_qty = float(item.coarse_packs_needed)
        elif item.needs_review:
            row.note = " + ".join(item.review_parts)
            # 2026-09-13 code review — structured twin of the note breakdown above, read
            # verbatim by the frontend's "use X" quick-resolve buttons instead of regex-
            # parsing `note` back apart (which broke once a conversion-notes fragment could
            # get appended to the same string below). See consolidation.ReviewOption.
            row.review_options_json = json.dumps(
                [{"quantity": o.quantity, "unit": o.unit} for o in item.review_options]
            )
        elif item.is_no_scale:
            row.note = "to taste"
        else:
            rows = (
                db.query(ProductUnit)
                .filter(ProductUnit.ingredient_name == item.name)
                .all()
            )
            required, opts, _kind = session_pack_resolution.pack_options_for(item, rows)
            resolution = purchase_units.resolve_packs(required, opts) if opts else None
            if resolution is not None:
                row.display_qty = resolution.display_qty
                row.purchase_qty = resolution.total_purchased
                row.purchase_label = (
                    resolution.counts[0][0]
                    if len(resolution.counts) == 1
                    else resolution.display_qty
                )
                if resolution.show_overage:
                    row.note = session_pack_resolution.overage_note(resolution.overage, item)
            if item.also_to_taste:
                row.note = f"{row.note} (+ to taste)" if row.note else "(+ to taste)"

        # 2026-09-10 (Ingredient Aliases quantity/unit transform, e.g. "lemon juice" ->
        # "lemon") — shown per the maintainer's call: an alias-with-transform conversion is
        # an approximation (a lemon's juice yield varies), so it's surfaced rather than fully
        # silent, unlike a plain name-only alias. Appended after every other note branch
        # above so it combines with a needs_review breakdown / overage / to-taste marker
        # rather than replacing it.
        if item.conversion_notes:
            frag = "from " + ", ".join(item.conversion_notes)
            row.note = f"{row.note} ({frag})" if row.note else frag

    for stale in existing.values():
        db.delete(stale)

    db.commit()
    logger.info(
        "Session consolidated: session_id=%s items=%d overrides=%d",
        session_id,
        len(items),
        len(overrides or []),
    )
    db.refresh(session)
    rows = sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)
    return rows, items

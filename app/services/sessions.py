"""Planning-session business logic (Phase 4) — session CRUD and ordered slot
management. Plain Python / SQLAlchemy only, no `fastapi` import — see CLAUDE.md >
Code Architecture & Maintainability. Routers translate the exceptions below into
the {"ok": false, "error": ...} envelope centrally in app/main.py.

A slot (`session_recipes` row) is either a real recipe or a 'leftovers' marker.
Per CLAUDE.md > Code Architecture > file size discipline, the leftovers path is its
own function (`add_leftovers_slot`), not an `if slot_type == ...` branch inside the
recipe path.
"""

# NOTE (file size): ~410 lines. The `consolidate_session` orchestrator could move to its
# own module at the Phase 3.9 M-review. See CLAUDE.md > File size and scope discipline.

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.catalog import ProductUnit, Staple
from app.models.planning import PlanningSession, SessionChecklistItem, SessionRecipe
from app.schemas.sessions import (
    LeftoversSlotCreate,
    PlanningSessionCreate,
    PlanningSessionUpdate,
    SessionOverride,
    SessionRecipeCreate,
    SessionSlotUpdate,
)
from app.services import consolidation, purchase_units, scaling
from app.services import recipes as recipes_service
from app.services.scaling import DEFAULT_TARGET_SERVINGS

logger = logging.getLogger(__name__)

# Pack-unit strings we know how to normalise, grouped by dimension — mirrors
# consolidation._G_PER / _ML_PER so pack sizes line up with consolidated quantities.
_PACK_G = {"g": 1.0, "kg": 1000.0}
_PACK_ML = {"ml": 1.0, "l": 1000.0, "tsp": 5.0, "tbsp": 20.0, "cup": 250.0}
_PACK_COUNT = {"each", "ea", "unit", "count", ""}


class SessionNotFoundError(Exception):
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Planning session {session_id} not found")


class SessionSlotNotFoundError(Exception):
    def __init__(self, session_id: int, slot_id: int) -> None:
        self.session_id = session_id
        self.slot_id = slot_id
        super().__init__(f"Slot {slot_id} not found on session {session_id}")


class SlotOrderMismatchError(Exception):
    """The id list passed to reorder isn't exactly this session's current slot ids."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(
            f"Reorder for session {session_id} must list exactly its current slot ids"
        )


# --- sessions ---------------------------------------------------------------


def create_session(db: Session, data: PlanningSessionCreate) -> PlanningSession:
    session = PlanningSession(label=(data.label.strip() if data.label else None))
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("Planning session created: id=%s label=%r", session.id, session.label)
    return session


def get_session(db: Session, session_id: int) -> PlanningSession:
    session = db.get(PlanningSession, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    return session


def list_sessions(
    db: Session, *, limit: int = 50, offset: int = 0, status: str | None = None
) -> tuple[list[PlanningSession], int]:
    """(page of sessions, total). Newest first — this is a history-style list."""
    query = db.query(PlanningSession)
    if status:
        query = query.filter(PlanningSession.status == status)
    total = query.count()
    sessions = (
        query.order_by(PlanningSession.created_at.desc(), PlanningSession.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return sessions, total


def update_session(
    db: Session, session_id: int, data: PlanningSessionUpdate
) -> PlanningSession:
    session = get_session(db, session_id)
    changes = data.model_dump(exclude_unset=True)
    if "label" in changes:
        changes["label"] = changes["label"].strip() if changes["label"] else None
    for field, value in changes.items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    logger.info("Planning session updated: id=%s fields=%s", session_id, list(changes.keys()))
    return session


def archive_session(db: Session, session_id: int) -> PlanningSession:
    """Convenience for the common status change — sets status='archived'. There is no
    hard delete for sessions (CLAUDE.md > Build Phases > Phase 4 Chunk 4.4)."""
    session = get_session(db, session_id)
    session.status = "archived"
    db.commit()
    db.refresh(session)
    logger.info("Planning session archived: id=%s", session_id)
    return session


# --- slots ----------------------------------------------------------------


def _next_sort_order(session: PlanningSession) -> int:
    return max((s.sort_order for s in session.recipes), default=-1) + 1


def _get_slot(db: Session, session_id: int, slot_id: int) -> SessionRecipe:
    slot = db.get(SessionRecipe, slot_id)
    if slot is None or slot.session_id != session_id:
        raise SessionSlotNotFoundError(session_id, slot_id)
    return slot


def add_session_recipe(
    db: Session, session_id: int, data: SessionRecipeCreate
) -> SessionRecipe:
    """Add a real recipe slot. Validates the recipe exists (reusing
    recipes_service.RecipeNotFoundError -> 404). `scaled_servings` defaults to the
    household target when the caller doesn't set one."""
    session = get_session(db, session_id)
    recipes_service.get_recipe(db, data.recipe_id)  # raises RecipeNotFoundError

    slot = SessionRecipe(
        session_id=session.id,
        recipe_id=data.recipe_id,
        slot_type="recipe",
        day_of_week=data.day_of_week,
        scaled_servings=data.scaled_servings or DEFAULT_TARGET_SERVINGS,
        sort_order=data.sort_order if data.sort_order is not None else _next_sort_order(session),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session recipe slot added: session_id=%s slot_id=%s recipe_id=%s servings=%s",
        session_id,
        slot.id,
        slot.recipe_id,
        slot.scaled_servings,
    )
    return slot


def add_leftovers_slot(
    db: Session, session_id: int, data: LeftoversSlotCreate
) -> SessionRecipe:
    """Add a non-recipe 'leftovers' slot: no recipe_id, scaled_servings pinned to 0,
    contributes nothing to consolidation."""
    session = get_session(db, session_id)
    slot = SessionRecipe(
        session_id=session.id,
        recipe_id=None,
        slot_type="leftovers",
        day_of_week=data.day_of_week,
        scaled_servings=0,
        sort_order=data.sort_order if data.sort_order is not None else _next_sort_order(session),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session leftovers slot added: session_id=%s slot_id=%s day=%s",
        session_id,
        slot.id,
        slot.day_of_week,
    )
    return slot


def update_slot(
    db: Session, session_id: int, slot_id: int, data: SessionSlotUpdate
) -> SessionRecipe:
    slot = _get_slot(db, session_id, slot_id)
    changes = data.model_dump(exclude_unset=True)
    # scaled_servings is inert on a leftovers slot — keep it pinned at 0.
    if slot.slot_type == "leftovers":
        changes.pop("scaled_servings", None)
    for field, value in changes.items():
        if value is not None:
            setattr(slot, field, value)
    db.commit()
    db.refresh(slot)
    logger.info(
        "Session slot updated: session_id=%s slot_id=%s fields=%s",
        session_id,
        slot_id,
        list(changes.keys()),
    )
    return slot


def remove_slot(db: Session, session_id: int, slot_id: int) -> None:
    slot = _get_slot(db, session_id, slot_id)
    db.delete(slot)
    db.commit()
    logger.info("Session slot removed: session_id=%s slot_id=%s", session_id, slot_id)


def reorder_slots(db: Session, session_id: int, ordered_ids: list[int]) -> list[SessionRecipe]:
    """Set sort_order from position. `ordered_ids` must be exactly this session's current
    slot ids (any order) — a partial or foreign list is rejected rather than silently
    reordering a subset."""
    session = get_session(db, session_id)
    current = {s.id for s in session.recipes}
    if set(ordered_ids) != current or len(ordered_ids) != len(current):
        raise SlotOrderMismatchError(session_id)
    by_id = {s.id: s for s in session.recipes}
    for position, slot_id in enumerate(ordered_ids):
        by_id[slot_id].sort_order = position
    db.commit()
    logger.info("Session slots reordered: session_id=%s order=%s", session_id, ordered_ids)
    db.refresh(session)
    return sorted(session.recipes, key=lambda s: s.sort_order)


# --- consolidation (Chunk 4.6) --------------------------------------------
#
# Orchestrator: pulls the session's scaled ingredient lines out of the DB, runs them
# through the pure consolidation + purchase_units services, and upserts
# session_checklist_items. The rounding/unit rules themselves live in
# services/consolidation.py; this function is the DB plumbing around them. See CLAUDE.md >
# Scaling Logic and > Build Phases > Phase 4 > Chunk 4.6.


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


def _scaled_lines(
    session: PlanningSession, override_map: dict[str, SessionOverride]
) -> list[consolidation.IngredientLine]:
    """Scaled ingredient lines with the *effective* name (and, for M8, amount/unit) already
    resolved: per-recipe `resolved_ingredient` / `resolved_quantity` (fallback `name` /
    `quantity`), then a session-only override keyed off that resolved name.
    `consolidation.consolidate()` itself does no substitution (Phase 3.9 M4/M8)."""
    lines: list[consolidation.IngredientLine] = []
    for slot in session.recipes:
        if slot.slot_type != "recipe" or slot.recipe is None:
            continue  # leftovers slots contribute nothing
        factor = scaling.scaling_factor(slot.recipe.base_servings, slot.scaled_servings)
        for ing in slot.recipe.ingredients:
            base = ing.resolved_ingredient or ing.name
            src_qty, src_unit = _effective_source(ing)
            sq = scaling.scale_quantity(src_qty, src_unit, factor)
            name, qty, unit = base, sq.quantity, sq.unit
            ov = override_map.get(_norm(base))
            if ov is not None:
                name, qty, unit = _apply_session_override(
                    name, qty, unit, sq.scaled, ov
                )
            lines.append(
                consolidation.IngredientLine(
                    name=name, quantity=qty, unit=unit, is_no_scale=not sq.scaled
                )
            )
    return lines


def _pack_options_for(
    item: consolidation.ConsolidatedItem, rows: list[ProductUnit]
) -> tuple[float, list[purchase_units.PackOption], str]:
    """(required_in_base, [PackOption in the same base], base_kind). base_kind is
    'mass' | 'volume' | 'count' | 'unit:<x>'. Rows whose unit doesn't match the item's
    dimension are dropped."""
    unit = (item.unit or "").strip().lower()
    if unit in _PACK_G or unit in ("g", "kg"):
        base_kind, factor = "mass", (1000.0 if unit == "kg" else 1.0)
        required = (item.quantity or 0.0) * factor
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty * _PACK_G[(r.purchase_unit or "").lower()])
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_G
        ]
        return required, opts, base_kind
    if unit in _PACK_ML:
        base_kind = "volume"
        required = (item.quantity or 0.0) * _PACK_ML[unit]
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty * _PACK_ML[(r.purchase_unit or "").lower()])
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_ML
        ]
        return required, opts, base_kind
    if item.unit is None:  # bare count
        required = item.quantity or 0.0
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty)
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_COUNT
        ]
        return required, opts, "count"
    # free-text unit — only match pack rows carrying the same unit string
    required = item.quantity or 0.0
    opts = [
        purchase_units.PackOption(r.purchase_label, r.purchase_qty)
        for r in rows
        if (r.purchase_unit or "").lower() == unit
    ]
    return required, opts, f"unit:{unit}"


def _overage_note(overage_base: float, item: consolidation.ConsolidatedItem) -> str:
    """overage is in the consolidation base (g/ml/count); render it in the item's unit."""
    u = (item.unit or "").strip().lower()
    if u == "kg":
        return f"{consolidation._fmt_qty(overage_base / 1000)} kg spare"
    if u == "l":
        return f"{consolidation._fmt_qty(overage_base / 1000)} L spare"
    if u in ("g", "ml"):
        return f"{consolidation._fmt_qty(overage_base)} {u} spare"
    if item.unit is None:
        return f"{consolidation._fmt_qty(overage_base)} spare"
    return f"{consolidation._fmt_qty(overage_base)} {item.unit} spare"


def consolidate_session(
    db: Session, session_id: int, *, overrides: list[SessionOverride] | None = None
) -> list[SessionChecklistItem]:
    """Rebuild the consolidated checklist for a session. Upsert, not wipe: computed
    fields are recomputed, new lines added, gone lines removed, but per-line state
    (have_it / add_to_list / already_on_anylist / anylist_item_id) is PRESERVED for
    lines that persist (CLAUDE.md > Scaling Logic > re-running consolidation)."""
    session = get_session(db, session_id)

    # Session-only overrides — client-held, not written anywhere (Phase 3.9 M4/M8). Per-recipe
    # `resolved_ingredient` / `resolved_quantity` is applied inside _scaled_lines; there is no
    # global rule map. Keyed by normalised original name; the whole override (incl. any M8
    # equivalence pair) is carried through.
    override_map = {_norm(ov.original_name): ov for ov in (overrides or [])}
    items = consolidation.consolidate(_scaled_lines(session, override_map))

    staple_names = {s.name for s in db.query(Staple).all()}
    existing = {ci.ingredient_name: ci for ci in session.checklist_items}

    for item in items:
        row = existing.pop(item.name, None)
        if row is None:
            row = SessionChecklistItem(session_id=session.id, ingredient_name=item.name)
            db.add(row)

        row.is_staple = item.name in staple_names
        # reset computed fields every run
        row.total_quantity = item.quantity
        row.total_unit = item.unit
        row.purchase_label = None
        row.purchase_qty = None
        row.display_qty = None
        row.needs_review = item.needs_review
        row.note = None

        if item.needs_review:
            row.note = " + ".join(item.review_parts)
        elif item.is_no_scale:
            row.note = "to taste"
        else:
            rows = (
                db.query(ProductUnit)
                .filter(ProductUnit.ingredient_name == item.name)
                .all()
            )
            required, opts, _kind = _pack_options_for(item, rows)
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
                    row.note = _overage_note(resolution.overage, item)
            if item.also_to_taste:
                row.note = f"{row.note} (+ to taste)" if row.note else "(+ to taste)"

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
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)

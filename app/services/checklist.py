"""Checklist screen orchestrator (Phase 5) — load the consolidated checklist for a session,
match it against the current AnyList list to pre-tick, and (Chunk 5.6) push the result.

Plain Python / SQLAlchemy + the ``anylist_client`` interface; no ``fastapi`` import. Routers
(app/routers/checklist.py) translate the exceptions below into the ``{"ok": ...}`` envelope
centrally in app/main.py. See CLAUDE.md > Checklist Screen Logic and > AnyList Push Logic.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.history import ShoppingHistory
from app.schemas.coarse_ingredients import CoarseIngredientCreate
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.settings import ProductUnitCreate
from app.schemas.substitutions import RememberedSubstitutionCreate
from app.services import anylist_client
from app.services import checklist_display
from app.models.planning import SessionChecklistItem
from app.services import coarse_ingredients as coarse_ingredients_service
from app.services import ingredient_aliases as ingredient_aliases_service
from app.services import progress_tracker
from app.services import session_merges
from app.services import sessions as sessions_service
from app.services import settings as settings_service
from app.services import substitutions as substitutions_service
from app.services import text_normalize
from app.services import usuals as usuals_service
from app.services.anylist_client import AnyListError, PushItem

logger = logging.getLogger(__name__)


class ChecklistItemNotFoundError(Exception):
    """404 CHECKLIST_ITEM_NOT_FOUND."""

    def __init__(self, session_id: int, item_id: int) -> None:
        self.session_id = session_id
        self.item_id = item_id
        super().__init__(f"Checklist item {item_id} not found on session {session_id}")


class SessionAlreadyPushedError(Exception):
    """The session was already pushed to AnyList; re-push needs ?force=true.
    409 SESSION_ALREADY_PUSHED."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} has already been pushed to AnyList")


# --- name matching --------------------------------------------------------------------


def _norm(s: str) -> str:
    """Delegates to the shared text_normalize.base_norm() (2026-09-27) — NOT the full
    normalise_ingredient_name(), since _names_match() below applies singularisation itself, as
    its own explicit fallback tier (see _singularise)."""
    return text_normalize.base_norm(s or "")


def _singularise(s: str) -> str:
    """Delegates to the shared, hardened text_normalize.singularise() (2026-09-27) — this used
    to be its own weaker, local copy (missing the -us guard and irregular -ies/-ves endings).
    `anylist_name` is raw external text this app doesn't control, so _names_match() below still
    needs its own explicit singularise fallback tier even though `ingredient_name` on our side
    is already fully normalised by the time it gets here (CLAUDE.md > Checklist Screen Logic:
    "fuzzy name match — normalised lowercase, strip plurals if needed"). A false negative just
    means the user ticks the item by hand; a false positive would pre-tick the wrong thing."""
    return text_normalize.singularise(s)


def _names_match(ingredient_name: str, anylist_name: str | None) -> bool:
    a, b = _norm(ingredient_name), _norm(anylist_name or "")
    if not a or not b:
        return False
    return a == b or _singularise(a) == _singularise(b)


def _find_match(
    ingredient_name: str, anylist_items: list[anylist_client.AnyListItem]
) -> anylist_client.AnyListItem | None:
    return next((i for i in anylist_items if _names_match(ingredient_name, i.name)), None)


# --- load -----------------------------------------------------------------------------


def load_checklist(
    db: Session, session_id: int
) -> tuple[list[SessionChecklistItem], bool, str | None, dict[str, list]]:
    """(checklist items, anylist_ok, anylist_detail, recipe_breakdown). Re-runs the AnyList
    match every call (the spec's "at checklist screen load" step). Upsert on the existing
    rows: `already_on_anylist` / `anylist_item_id` are recomputed *only when the AnyList fetch
    succeeds* (a transient failure must not wipe a good match); `have_it` is only ever
    *upgraded* from 'unknown' to 'yes' by a pre-tick, never downgraded. Never touches
    `add_to_list`.

    **2026-09-30 (chunk 7.3, Review→Checklist merge):** used to raise `ChecklistNotReadyError`
    if the session had no consolidated checklist yet, requiring a caller (the now-deleted
    Review screen) to run `POST /sessions/{id}/consolidate` first. Now calls
    `consolidate_session_with_breakdown()` itself, every load, so Checklist works standalone.
    Safe to do unconditionally: `consolidate_session()`'s upsert is already documented as
    non-destructive to per-line state (`have_it`/`add_to_list`/`already_on_anylist` preserved
    for lines that persist, only computed fields recomputed) — the exact property the
    upgrade-only pre-tick logic below already depends on. `recipe_breakdown` (CLAUDE.md >
    "Which recipe is this ingredient from") is a byproduct of that same pass, no second
    consolidation needed for it — see `docs/scaling-and-consolidation.md`, no longer
    review-screen-only now that Checklist is the one place this runs."""
    session = sessions_service.get_session(db, session_id)  # raises SessionNotFoundError
    _rows, breakdown = sessions_service.consolidate_session_with_breakdown(db, session_id)
    # Same Session identity map -> `session` now reflects the just-committed consolidate
    # (SQLAlchemy expires attributes on commit; the next access below re-queries fresh).
    items = list(session.checklist_items)

    anylist_items: list[anylist_client.AnyListItem] = []
    anylist_ok, anylist_detail = True, None
    try:
        anylist_items = anylist_client.get_items()
    except anylist_client.AnyListDisabledError as exc:
        anylist_ok, anylist_detail = False, str(exc)
    except AnyListError as exc:
        anylist_ok, anylist_detail = False, str(exc)
        logger.warning("Checklist load: AnyList fetch failed, pre-tick skipped — %s", exc)

    for ci in items:
        if not anylist_ok:
            continue  # keep whatever match state was there; don't wipe it on a transient fail
        match = _find_match(ci.ingredient_name, anylist_items)
        if match is not None:
            ci.already_on_anylist = True
            ci.anylist_item_id = match.identifier
            if ci.have_it == "unknown":
                ci.have_it = "yes"  # pre-tick; user can still untick
        else:
            ci.already_on_anylist = False
            ci.anylist_item_id = None

    db.commit()
    db.refresh(session)
    ordered = sorted(session.checklist_items, key=lambda c: c.ingredient_name or "")
    logger.info(
        "Checklist loaded: session_id=%s items=%d anylist_ok=%s on_list=%d",
        session_id,
        len(ordered),
        anylist_ok,
        sum(1 for c in ordered if c.already_on_anylist),
    )
    return ordered, anylist_ok, anylist_detail, breakdown


def due_usuals(db: Session) -> list:
    """"The usuals" items that are currently due, as ChecklistUsualRead. Real implementation
    lands in Chunk 5.4 (services/usuals.py + the usual_items table); until then the checklist
    simply has no usuals group."""
    try:
        from app.services import usuals as usuals_service  # optional until Chunk 5.4
    except ImportError:
        return []
    return usuals_service.due_as_checklist_rows(db)


# --- per-item edits ------------------------------------------------------------------


def _get_item(db: Session, session_id: int, item_id: int) -> SessionChecklistItem:
    row = db.get(SessionChecklistItem, item_id)
    if row is None or row.session_id != session_id:
        raise ChecklistItemNotFoundError(session_id, item_id)
    return row


def update_item(
    db: Session,
    session_id: int,
    item_id: int,
    *,
    have_it: str | None = None,
    add_to_list: bool | None = None,
) -> SessionChecklistItem:
    row = _get_item(db, session_id, item_id)
    if have_it is not None:
        row.have_it = have_it
    if add_to_list is not None:
        row.add_to_list = add_to_list
    db.commit()
    db.refresh(row)
    logger.info(
        "Checklist item updated: session_id=%s item_id=%s have_it=%s add_to_list=%s",
        session_id, item_id, row.have_it, row.add_to_list,
    )
    return row


def resolve_item(
    db: Session, session_id: int, item_id: int, *, total_quantity: float, total_unit: str | None
) -> SessionChecklistItem:
    """Commit a single total for a Chunk 4.6 irreconcilable-units line and clear the flag.

    ``review_resolved_by_user`` is set so a later ``consolidate_session()`` re-run (e.g. after
    adding another recipe) doesn't silently re-flag and reset this choice while the same
    ingredient still conflicts — 2026-09-10 hand-testing ("doesn't remember amounts under
    review"). See CLAUDE.md > Scaling Logic > re-running consolidation."""
    row = _get_item(db, session_id, item_id)
    row.total_quantity = total_quantity
    row.total_unit = total_unit
    row.needs_review = False
    row.note = None
    row.review_options_json = None  # resolved -- no more quick-picks to offer for this line
    row.review_resolved_by_user = True
    db.commit()
    db.refresh(row)
    logger.info(
        "Checklist item resolved: session_id=%s item_id=%s -> %s %s",
        session_id, item_id, total_quantity, total_unit,
    )
    return row


# --- merge (Fix 3, F3.3 — CLAUDE.md > Deferred Decisions > checklist-time merge) -----------

_HAVE_IT_STRENGTH = {"no": 2, "yes": 1, "unknown": 0, "partial": 0}


def merge_items(
    db: Session,
    session_id: int,
    *,
    item_names: list[str],
    canonical_name: str,
    remember: bool,
    alias_qty: float | None = None,
    alias_unit: str | None = None,
    canonical_qty: float | None = None,
    canonical_unit: str | None = None,
) -> list[SessionChecklistItem]:
    """Fold 2+ already-consolidated checklist lines into one, either for this session only
    (`remember=False` -> `session_merges.add_session_merge()`) or as a durable household
    preference (`remember=True` -> a real `ingredient_aliases` row per non-canonical name).
    Pre-push only — merging after a push would leave an un-cleanable stray duplicate on the
    real AnyList list.

    The equivalence pair, when given, applies uniformly to every non-canonical name in
    `item_names` — the request schema carries exactly one pair, matching the checklist UI's own
    simple "select 2+, keep one name, optionally set one ratio" shape (F3.4); a merge needing a
    *different* ratio per member isn't supported by this action (same "don't build past what's
    asked for" discipline as everywhere else in this app).

    State handling: `have_it`/`add_to_list` are read from every named row *before*
    `consolidate_session()` runs (which will delete the merged-away rows via its own existing,
    unmodified stale-row cleanup) and the strongest value across all of them is written onto
    the surviving canonical row *after* — so a merge never silently loses an in-progress
    decision (`session_checklist_items` is this app's own documented ephemeral,
    recomputed-every-consolidate cache, not persistent household data — this preservation step
    is on top of, not instead of, that existing convention)."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)

    rows = {
        row.ingredient_name: row
        for row in db.query(SessionChecklistItem)
        .filter(
            SessionChecklistItem.session_id == session_id,
            SessionChecklistItem.ingredient_name.in_(item_names),
        )
        .all()
    }
    have_it = "unknown"
    add_to_list = False
    for row in rows.values():
        if _HAVE_IT_STRENGTH.get(row.have_it, 0) > _HAVE_IT_STRENGTH.get(have_it, 0):
            have_it = row.have_it
        add_to_list = add_to_list or row.add_to_list

    members = [n for n in item_names if n != canonical_name]
    if remember:
        # Explicitly not caught/suppressed: a name already aliased elsewhere raises
        # DuplicateIngredientAliasError, surfaced as a normal structured 409 the user can act
        # on (pick a different canonical, or fix the existing alias first) — same "surface it,
        # don't silently swallow it" convention as every other structured error in this app.
        for member in members:
            ingredient_aliases_service.create_alias(
                db,
                IngredientAliasCreate(
                    alias_name=member, canonical_name=canonical_name,
                    alias_qty=alias_qty, alias_unit=alias_unit,
                    canonical_qty=canonical_qty, canonical_unit=canonical_unit,
                ),
            )
    else:
        for member in members:
            session_merges.add_session_merge(
                db, session_id, member, canonical_name,
                alias_qty=alias_qty, alias_unit=alias_unit,
                canonical_qty=canonical_qty, canonical_unit=canonical_unit,
            )

    sessions_service.consolidate_session(db, session_id)

    canonical_row = (
        db.query(SessionChecklistItem)
        .filter(
            SessionChecklistItem.session_id == session_id,
            SessionChecklistItem.ingredient_name == canonical_name,
        )
        .first()
    )
    if canonical_row is not None:
        if _HAVE_IT_STRENGTH.get(have_it, 0) > _HAVE_IT_STRENGTH.get(canonical_row.have_it, 0):
            canonical_row.have_it = have_it
        canonical_row.add_to_list = canonical_row.add_to_list or add_to_list
        db.commit()
        db.refresh(canonical_row)

    logger.info(
        "Checklist items merged: session_id=%s %r -> %r remember=%s",
        session_id, item_names, canonical_name, remember,
    )
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)


# --- ingredient panel (2026-09-30, chunk 7.5) ---------------------------------------------
#
# Four sections of the Checklist ingredient panel (CLAUDE.md > Checklist Screen Logic) — each
# writes either a session-scoped "this list only" edit (session_ingredient_merges, via
# services/session_merges.py) or a permanent one (an existing global Settings table), per its
# own `remember` flag. All four are pre-push only, same reasoning as merge_items() above:
# renaming/re-resolving an ingredient after push risks a stray duplicate or a confusing
# mismatch against what was actually sent to AnyList. Each re-consolidates before returning so
# the effect is immediately visible, same pattern as merge_items().


def substitute_item(
    db: Session,
    session_id: int,
    item_id: int,
    *,
    substitute_name: str,
    original_qty: float | None,
    original_unit: str | None,
    substitute_qty: float | None,
    substitute_unit: str | None,
    remember: bool,
) -> list[SessionChecklistItem]:
    """The ingredient panel's Substitute chip. `remember=True` writes a
    `remembered_substitutions` quick-pick — NOT the recipe's own `resolved_ingredient` (see
    `schemas.checklist.ChecklistItemSubstituteRequest`'s docstring for why baking into a
    specific recipe is deliberately not attempted here)."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)
    item = _get_item(db, session_id, item_id)
    member_name = item.ingredient_name
    substitute_norm = text_normalize.normalise_ingredient_name(substitute_name)

    if remember:
        substitutions_service.create_substitution(
            db,
            RememberedSubstitutionCreate(
                original_name=member_name,
                substitute_name=substitute_norm,
                original_qty=original_qty,
                original_unit=original_unit,
                substitute_qty=substitute_qty,
                substitute_unit=substitute_unit,
            ),
        )
    else:
        session_merges.add_session_substitute(
            db, session_id, member_name, substitute_norm,
            alias_qty=original_qty, alias_unit=original_unit,
            canonical_qty=substitute_qty, canonical_unit=substitute_unit,
        )

    sessions_service.consolidate_session(db, session_id)
    logger.info(
        "Checklist item substituted: session_id=%s %r -> %r remember=%s",
        session_id, member_name, substitute_norm, remember,
    )
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)


def alias_item(
    db: Session, session_id: int, item_id: int, *, alias_name: str, remember: bool
) -> list[SessionChecklistItem]:
    """The ingredient panel's Alias chip — "same item as <alias_name>". Mechanically identical
    to a 2-item Merge (member_name -> canonical_name fold); the only difference is that
    `alias_name` is freely typed rather than picked from another checklist row, so this
    doesn't need merge_items()'s have_it/add_to_list-preservation logic (there's no existing
    row for the typed name to preserve state from)."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)
    item = _get_item(db, session_id, item_id)
    canonical_name = item.ingredient_name
    alias_norm = text_normalize.normalise_ingredient_name(alias_name)

    if remember:
        ingredient_aliases_service.create_alias(
            db, IngredientAliasCreate(alias_name=alias_norm, canonical_name=canonical_name)
        )
    else:
        session_merges.add_session_merge(db, session_id, alias_norm, canonical_name)

    sessions_service.consolidate_session(db, session_id)
    logger.info(
        "Checklist item aliased: session_id=%s %r -> %r remember=%s",
        session_id, alias_norm, canonical_name, remember,
    )
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)


def pack_size_item(
    db: Session,
    session_id: int,
    item_id: int,
    *,
    purchase_label: str,
    purchase_qty: float,
    purchase_unit: str | None,
    remember: bool,
) -> list[SessionChecklistItem]:
    """The ingredient panel's Pack size chip. `remember=False` behaves like the existing
    inline "+ Add pack size" form (`packSizeForm()` in checklist.js) except it doesn't write
    to `product_units` at all — session-scoped only, via `session_ingredient_merges`."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)
    item = _get_item(db, session_id, item_id)
    member_name = item.ingredient_name

    if remember:
        settings_service.create_product_unit(
            db,
            ProductUnitCreate(
                ingredient_name=member_name,
                purchase_label=purchase_label,
                purchase_qty=purchase_qty,
                purchase_unit=purchase_unit,
                notes=None,
            ),
        )
    else:
        session_merges.add_session_pack_override(
            db, session_id, member_name, purchase_label, purchase_qty, purchase_unit
        )

    sessions_service.consolidate_session(db, session_id)
    logger.info(
        "Checklist item pack size set: session_id=%s %r -> %s %s %r remember=%s",
        session_id, member_name, purchase_qty, purchase_unit, purchase_label, remember,
    )
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)


def coarse_item(
    db: Session,
    session_id: int,
    item_id: int,
    *,
    purchase_label: str | None,
    recipes_per_pack: int,
    remember: bool,
) -> list[SessionChecklistItem]:
    """The ingredient panel's Coarse item chip — CLAUDE.md > Ingredient Unit Handling >
    Layer D, applied "this list only" when not remembered."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)
    item = _get_item(db, session_id, item_id)
    member_name = item.ingredient_name

    if remember:
        coarse_ingredients_service.create_coarse_ingredient(
            db,
            CoarseIngredientCreate(
                name=member_name,
                purchase_label=purchase_label,
                recipes_per_pack=recipes_per_pack,
                notes=None,
            ),
        )
    else:
        session_merges.add_session_coarse_override(
            db, session_id, member_name, recipes_per_pack, purchase_label
        )

    sessions_service.consolidate_session(db, session_id)
    logger.info(
        "Checklist item marked coarse: session_id=%s %r recipes_per_pack=%s remember=%s",
        session_id, member_name, recipes_per_pack, remember,
    )
    return sorted(session.checklist_items, key=lambda ci: ci.ingredient_name)


# --- push (Chunk 5.6) ---------------------------------------------------------------


def _anylist_quantity(item: SessionChecklistItem) -> str | None:
    """The 'need' amount for AnyList's quantity field (CLAUDE.md > AnyList Push Logic step 3)
    — how much to actually buy, not the pack-count string. Falls back to the pack breakdown
    only when there's no plain numeric total at all (a coarse ingredient, e.g. "2 × bunch",
    which has no numeric total by design — CLAUDE.md > Ingredient Unit Handling > Layer D).

    **Maintainer request, Chunk 5.7 live-verification (2026-09-12).** Previously this
    function (then `_display_quantity`) sent the pack-breakdown string itself (e.g.
    "2 × 500g pack") to AnyList's quantity field. That's moved to the note instead (see
    `_anylist_note`) — the quantity field is reserved for the plain figure a shopper needs,
    not a sentence describing how it was packed."""
    if item.total_quantity is not None:
        n = item.total_quantity
        n = str(int(n)) if n == int(n) else f"{n:g}"
        return f"{n} {item.total_unit}".strip() if item.total_unit else n
    if item.display_qty:
        return item.display_qty
    return None


def _anylist_note(item: SessionChecklistItem) -> str | None:
    """The note sent to AnyList's ``details`` field: pack-size context (moved here from the
    quantity field, see `_anylist_quantity`) plus whatever the checklist's own `.note` already
    carries — an overage hint, "to taste", a needs_review breakdown, an alias conversion note
    (CLAUDE.md > Scaling Logic, > Ingredient Aliases). Doesn't touch
    `session_checklist_items.note`/`.display_qty` themselves (the app's own checklist screen
    is unaffected) — this only shapes what crosses over to the real AnyList list."""
    parts = []
    if item.display_qty and item.total_quantity is not None:
        # Only a separate fragment when the quantity field carried the plain total instead of
        # it. A coarse item has no numeric total, so display_qty IS what went into quantity
        # above — repeating it here would be redundant.
        parts.append(item.display_qty)
    if item.note:
        parts.append(item.note)
    return " · ".join(parts) if parts else None


def push_to_anylist(
    db: Session,
    session_id: int,
    *,
    usual_ids: list[int] | None = None,
    force: bool = False,
    progress_token: str | None = None,
) -> dict:
    """Push the checklist to AnyList: every line the user needs (``add_to_list`` or
    ``have_it == 'no'``), plus any ticked due "usuals". Existing items are updated in place
    (no duplicates); new items are added. One batched call, then re-fetch + diff to confirm
    (CLAUDE.md > AnyList Push Logic and > AnyList spike findings). On completion the session
    is marked ``pushed`` and a ``shopping_history`` row is written — even if the diff wasn't
    fully confirmed (the discrepancies are recorded and returned; a not-marked-pushed session
    would re-push the confirmed items as duplicates on retry).

    ``progress_token``, when given, drives the real per-item push progress UI (CLAUDE.md >
    UI/UX > Real progress indicators) via ``progress_tracker`` — one step per pushed item
    (named by ingredient/usual name), reported active/done as ``anylist_client`` actually
    works through them. A falsy token makes this entirely a no-op, same as capture's."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed" and not force:
        raise SessionAlreadyPushedError(session_id)

    to_push = [
        ci for ci in session.checklist_items if ci.add_to_list or ci.have_it == "no"
    ]
    push_items = [
        PushItem(
            # 2026-09-27 — the natural-English display form ("chicken thighs", not the
            # matching key "chicken thigh") for THIS line's own resolved amount — see
            # services/checklist_display.py. AnyList's own fuzzy-match on re-push (_find_match
            # above) already tolerates a plural/singular difference via its own singularise
            # fallback, so this doesn't affect existing-item matching.
            name=checklist_display.display_name(db, ci.ingredient_name, ci.total_quantity, ci.total_unit).title(),
            quantity=_anylist_quantity(ci),
            existing_id=ci.anylist_item_id if ci.already_on_anylist else None,
            # 2026-09-10 hand-testing: a checklist note ("to taste", an overage hint like
            # "150 g spare", a needs_review breakdown) was silently dropped on push — it only
            # ever showed up on the app's own checklist screen. Carried through to AnyList's
            # details field (plus the pack breakdown, moved here at Chunk 5.7 — see
            # `_anylist_note`) so it's visible from the real list too.
            note=_anylist_note(ci),
        )
        for ci in to_push
    ]

    wanted_usual_ids = set(usual_ids or [])
    due_usuals = [u for u in usuals_service.due_items(db) if u.id in wanted_usual_ids]
    usual_names = {u.name.title() for u in due_usuals}
    push_items += [PushItem(name=u.name.title(), quantity=None) for u in due_usuals]

    progress_tracker.start(progress_token, [p.name for p in push_items])

    def _on_item(name: str, status: str) -> None:
        if status == "active":
            progress_tracker.step_active(progress_token, name)
        elif status == "done":
            progress_tracker.step_done(progress_token, name)

    result = anylist_client.add_or_increment_items(push_items, on_item=_on_item)  # AnyListError -> 502
    # Partition the connector's added/updated into ingredient lines vs usuals so the caller
    # doesn't double-count a usual (it also appears in `usuals_added`).
    added_ingredients = [n for n in result.added if n not in usual_names]
    updated_ingredients = [n for n in result.updated if n not in usual_names]

    # 2026-09-18 fault-finding, mechanism #3 (docs/build-status/anylist-fault-finding-spike.md):
    # without this, a checklist row that was just freshly ADDED stays already_on_anylist=False
    # (load_checklist() only ever sets it from an AnyList fetch that happened BEFORE this push),
    # so any push after this one -- in particular the UI's own "already pushed, push again?"
    # retry (static/js/checklist.js), which never reloads first -- treats it as new again and
    # duplicates it. `push_items[: len(to_push)]` lines up 1:1 with `to_push` (usuals are always
    # appended after). Deliberately NOT gated on `pi.existing_id is None` (a fresh add) alone —
    # 2026-09-20 fix (Phase B, same spike doc): a unit-bearing quantity update now goes through
    # delete+re-add under a *new* id too (see anylist_client.py's "replace" branch), and
    # `result.added_ids` covers that case exactly the same way. Without this, a replaced item's
    # row would keep pointing at the now-deleted old id, and every future push would look for a
    # phantom item forever.
    for ci, pi in zip(to_push, push_items[: len(to_push)]):
        if pi.name in result.added_ids:
            ci.already_on_anylist = True
            ci.anylist_item_id = result.added_ids[pi.name]

    session.status = "pushed"
    session.pushed_at = utcnow()
    if due_usuals:
        usuals_service.mark_added(db, [u.id for u in due_usuals], when=session.pushed_at)

    snapshot = {
        "ingredients": [
            {"name": p.name, "quantity": p.quantity, "existing": p.existing_id is not None}
            for p in push_items
        ],
        "confirmed": result.confirmed,
        "discrepancies": result.discrepancies,
    }
    history = ShoppingHistory(
        session_id=session_id,
        pushed_at=session.pushed_at,
        items_json=json.dumps(snapshot),
        anylist_response_json=json.dumps(
            {"raw": result.raw_response, "discrepancies": result.discrepancies}
        ),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    logger.info(
        "Checklist pushed: session_id=%s added=%d updated=%d usuals=%d confirmed=%s",
        session_id, len(added_ingredients), len(updated_ingredients), len(due_usuals), result.confirmed,
    )
    return {
        "session_id": session_id,
        "added": added_ingredients,
        "updated": updated_ingredients,
        "usuals_added": [u.name for u in due_usuals],
        "confirmed": result.confirmed,
        "discrepancies": result.discrepancies,
        "history_id": history.id,
    }

"""Checklist screen orchestrator (Phase 5) — load the consolidated checklist for a session,
match it against the current AnyList list to pre-tick, and (Chunk 5.6) push the result.

Plain Python / SQLAlchemy + the ``anylist_client`` interface; no ``fastapi`` import. Routers
(app/routers/checklist.py) translate the exceptions below into the ``{"ok": ...}`` envelope
centrally in app/main.py. See CLAUDE.md > Checklist Screen Logic and > AnyList Push Logic.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.history import ShoppingHistory
from app.schemas.coarse_ingredients import CoarseIngredientCreate
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.settings import ProductUnitCreate
from app.schemas.substitutions import RememberedSubstitutionCreate
from app.services import anylist_client
from app.services import checklist_display
from app.services import have_some
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
from app.services.anylist_client import (
    OUTCOME_ACTIVE,
    OUTCOME_FAILED,
    AnyListError,
    PushItem,
    PushItemResult,
)
from app.services.session_consolidation import HAVE_IT_STRENGTH

logger = logging.getLogger(__name__)


class ChecklistItemNotFoundError(Exception):
    """404 CHECKLIST_ITEM_NOT_FOUND."""

    def __init__(self, session_id: int, item_id: int) -> None:
        self.session_id = session_id
        self.item_id = item_id
        super().__init__(f"Checklist item {item_id} not found on session {session_id}")


class HaveSomeNotApplicableError(Exception):
    """"I have some" on a line with no single numeric amount (coarse / to taste / unresolved
    conflict). 422 HAVE_SOME_NOT_APPLICABLE."""

    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        super().__init__(f"Checklist item {item_id} has no single amount to take some off")


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
    """Is this AnyList item name the same shopping item as this checklist row's key?

    Three tiers, cheapest first. (1) Equal after lower-casing/space-folding. (2) The AnyList name
    run through the app's own key function ONCE equals the stored key — `ingredient_name` is
    already a key, so it must NOT be normalised a second time: `singularise` is not idempotent
    for some `-ses` words (cheeses -> "chees" -> "chee"), which made an item never match its own
    AnyList entry (Chunk 6.7, defect F; see docs/ingredient-handling.md). (3) The older
    both-sides-singularised comparison, kept so nothing that matched before stops matching.
    A false negative would add a duplicate on push; a false positive would update the wrong
    item, so tier 3 is deliberately no looser than it was."""
    a, b = _norm(ingredient_name), _norm(anylist_name or "")
    if not a or not b:
        return False
    if a == b:
        return True
    if text_normalize.normalise_ingredient_name(anylist_name or "") == ingredient_name:
        return True
    return _singularise(a) == _singularise(b)


def _matches(
    ingredient_name: str, anylist_items: list[anylist_client.AnyListItem]
) -> list[anylist_client.AnyListItem]:
    """Every AnyList item that is this ingredient, in list order."""
    return [i for i in anylist_items if _names_match(ingredient_name, i.name)]


def _best_match(
    matches: list[anylist_client.AnyListItem],
) -> anylist_client.AnyListItem | None:
    """The item a push should write to: an ACTIVE (uncrossed) one if there is any, else a
    crossed-off one (the push will re-add it uncrossed), else None. List order is arbitrary, so
    "first match" must never be allowed to pick last week's crossed-off item over this week's
    live one (Chunk 6.7, defect B)."""
    active = [m for m in matches if not m.checked]
    return (active or matches or [None])[0]


def _find_match(
    ingredient_name: str, anylist_items: list[anylist_client.AnyListItem]
) -> anylist_client.AnyListItem | None:
    """The ACTIVE item for this ingredient, or None. A crossed-off item is not "on the list" —
    it is already bought — so it must neither pre-tick the row as "Have it" nor count as on
    the list (Chunk 6.7, defect B). `_best_match` is the push-time twin that may return a
    crossed-off item."""
    active = [m for m in _matches(ingredient_name, anylist_items) if not m.checked]
    return active[0] if active else None


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
        # Only an ACTIVE (uncrossed) AnyList item counts as "already on the list" - a crossed-off
        # one is already bought and must neither pre-tick this row "Have it" nor be written to
        # as if it were live (Chunk 6.7, defect B; _find_match is active-only).
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
    row.note = None
    row.needs_review = False
    # review_options_json is deliberately KEPT: consolidation compares it to the fresh conflict to
    # notice a new amount arriving after this pick. SessionChecklistItem.review_options exposes
    # [] once needs_review is False, so no quick-picks are offered.
    row.review_resolved_by_user = True
    db.commit()
    db.refresh(row)
    logger.info(
        "Checklist item resolved: session_id=%s item_id=%s -> %s",
        session_id, item_id, f"{total_quantity} {total_unit}",
    )
    return row


def set_have_some(
    db: Session, session_id: int, item_id: int, *, quantity: float | None
) -> SessionChecklistItem:
    """Record how much of this ingredient the household already has ("I have some", Chunk 6.7
    batch 3). ``None`` or 0 clears it and leaves Have it / Need it as it was. The unit is always
    the row's own ``total_unit``. When what is had covers the whole need the row becomes Have it
    (the existing binary decision), so nothing is sent to AnyList for it.

    Refused for rows with no numeric total (coarse / "to taste") and for unresolved conflicts,
    where "how much" has no single unit to subtract in."""
    row = _get_item(db, session_id, item_id)
    if quantity is not None and quantity > 0:
        if row.total_quantity is None or row.needs_review:
            raise HaveSomeNotApplicableError(item_id)
        row.have_quantity = quantity
        row.have_unit = row.total_unit
        if have_some.covers_everything(row.total_quantity, row.total_unit, quantity, row.have_unit):
            row.have_it = "yes"
            row.add_to_list = False
    else:
        row.have_quantity = None
        row.have_unit = None
    db.commit()
    # Pack text ("Buy 1 x ...") depends on the amount to buy: recompute it.
    sessions_service.consolidate_session(db, session_id)
    db.refresh(row)
    logger.info(
        "Checklist item have-some: session_id=%s item_id=%s have=%s", session_id, item_id, quantity
    )
    return row


# --- merge (Fix 3, F3.3 — CLAUDE.md > Deferred Decisions > checklist-time merge) -----------

_HAVE_IT_STRENGTH = HAVE_IT_STRENGTH  # shared with session_consolidation (rename state-carry)


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
    created_alias_ids: list[int] | None = None,
    unconverted: list[str] | None = None,
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
    # The amount pair only converts a member whose unit is exactly the typed "alias unit"; any other
    # member is folded in by NAME only, amount unchanged (consolidation's fallback). That used to
    # happen silently - report which members it applied to so the UI can say so (2026-10-11,
    # Chunk 6.7), and log it.
    if unconverted is not None and alias_qty is not None and canonical_qty is not None:
        want = " ".join((alias_unit or "").lower().split())
        for member in members:
            row = rows.get(member)
            have = " ".join(((row.total_unit if row else None) or "").lower().split())
            if row is not None and have != want:
                unconverted.append(member)
        if unconverted:
            logger.warning(
                "Checklist merge: amount conversion not applied to %r (unit differs from %r); "
                "merged by name only (session_id=%s)", unconverted, alias_unit, session_id,
            )
    if remember:
        # Explicitly not caught/suppressed: a name already aliased elsewhere raises
        # DuplicateIngredientAliasError, surfaced as a normal structured 409 the user can act
        # on (pick a different canonical, or fix the existing alias first) — same "surface it,
        # don't silently swallow it" convention as every other structured error in this app.
        for member in members:
            alias = ingredient_aliases_service.create_alias(
                db,
                IngredientAliasCreate(
                    alias_name=member, canonical_name=canonical_name,
                    alias_qty=alias_qty, alias_unit=alias_unit,
                    canonical_qty=canonical_qty, canonical_unit=canonical_unit,
                ),
                source="merge",  # Settings tags these "from a checklist merge"
            )
            if created_alias_ids is not None:
                created_alias_ids.append(alias.id)  # so the caller can offer Undo
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


def undo_merge(
    db: Session,
    session_id: int,
    *,
    canonical_name: str,
    member_names: list[str],
    alias_ids: list[int] | None = None,
) -> list[SessionChecklistItem]:
    """Reverse a checklist merge (the Undo on the "Merged into …" toast, Chunk 6.7): delete the
    session-only merge rows for `member_names` (a "this list only" merge) and/or the saved aliases
    in `alias_ids` (a "merge every time"), re-consolidate so the members come back as their own
    lines, and give each restored line the same Need it / Have it decision the merged line had —
    otherwise Undo would silently drop a decision the user had made (the same class of loss as
    docs/anylist-push.md defect A). Idempotent: undoing something already undone changes nothing.
    Pre-push only, like the merge it reverses."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed":
        raise SessionAlreadyPushedError(session_id)
    merged = (
        db.query(SessionChecklistItem)
        .filter(SessionChecklistItem.session_id == session_id,
                SessionChecklistItem.ingredient_name == canonical_name)
        .first()
    )
    decision = (merged.have_it, merged.add_to_list) if merged is not None else ("unknown", False)

    for member in member_names:
        session_merges.remove_session_merge(db, session_id, member, "merge")
    for alias_id in alias_ids or []:
        try:
            ingredient_aliases_service.delete_alias(db, alias_id)
        except ingredient_aliases_service.IngredientAliasNotFoundError:
            db.rollback()  # already deleted (e.g. removed in Settings meanwhile): fine
        except Exception:  # noqa: BLE001 — anything else is NOT fine: say so, then carry on
            # 2026-10-07 logging audit: this used to swallow every failure silently, hiding real
            # database errors behind the "already deleted" case it was written for.
            logger.error(
                "Checklist merge undo: could not delete alias_id=%s (session_id=%s)",
                alias_id, session_id, exc_info=True,
            )
            db.rollback()
    sessions_service.consolidate_session(db, session_id)

    for member in member_names:
        row = (
            db.query(SessionChecklistItem)
            .filter(SessionChecklistItem.session_id == session_id,
                    SessionChecklistItem.ingredient_name == member)
            .first()
        )
        if row is not None and row.have_it == "unknown" and not row.add_to_list:
            row.have_it, row.add_to_list = decision
    db.commit()
    logger.info(
        "Checklist merge undone: session_id=%s %r <- %r alias_ids=%s",
        session_id, canonical_name, member_names, alias_ids or [],
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
        # "I have some": what is still to buy, not the full recipe need.
        n = have_some.amount_to_buy(
            item.total_quantity, item.total_unit, item.have_quantity, item.have_unit
        )
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


def _push_name(db: Session, ci: SessionChecklistItem, index: checklist_display.WordingIndex) -> str:
    """The name written to AnyList for one checklist row: the household's own wording for THIS
    line's resolved amount (services/checklist_display.py — guaranteed to normalise back to the
    row's matching key, so it always matches the row on the next push), title-cased by
    `text_normalize.title_case_name` (small words stay lower-case; no "Baker'S")."""
    return text_normalize.title_case_name(
        checklist_display.display_name(
            db, ci.ingredient_name,
            have_some.amount_to_buy(ci.total_quantity, ci.total_unit, ci.have_quantity, ci.have_unit),
            ci.total_unit, index,
        )
    )


def push_to_anylist(
    db: Session,
    session_id: int,
    *,
    usual_ids: list[int] | None = None,
    force: bool = False,
    progress_token: str | None = None,
) -> dict:
    """Push the checklist to AnyList so that every line the user needs (``add_to_list`` or
    ``have_it == 'no'``), plus any ticked due "usuals", ends up ON the list, NOT crossed off,
    with the right quantity and note — and prove it. See CLAUDE.md > AnyList Push Logic and
    docs/anylist-push.md (the authoritative description, runbook and test map).

    Flow: (1) read the list fresh — nothing is changed if this fails (502); (2) match each wanted
    line to an AnyList item BY NAME against that fresh read, preferring an active item over a
    crossed-off duplicate (a stale id from an earlier page load can't matter); (3) let the
    connector write and then read the list back — it reports a per-line outcome (added /
    updated / un-crossed / already-active / failed + reason), keyed by row, confirmed by the
    read-back and never by an HTTP status; (4) write the new AnyList ids back onto the rows, mark
    the session ``pushed`` and stamp the usuals — but only if every line was confirmed, so a
    partial failure leaves the session re-pushable without the "already pushed" prompt (the next
    push re-reads the list, leaves what landed alone, and retries only what failed); (5) record
    the whole per-line result in ``shopping_history`` and the log under one ``push_id``.

    ``progress_token``, when given, drives the real push progress UI via ``progress_tracker``:
    a coarse stage (reading / sending / confirming / done) plus one step per wanted line,
    addressed by row key. A falsy token makes all of it a no-op, same as capture's."""
    session = sessions_service.get_session(db, session_id)
    if session.status == "pushed" and not force:
        raise SessionAlreadyPushedError(session_id)

    push_id = uuid.uuid4().hex[:8]
    to_push = [
        ci for ci in session.checklist_items if ci.add_to_list or ci.have_it == "no"
    ]
    wanted_usual_ids = set(usual_ids or [])
    due_usuals = [u for u in usuals_service.due_items(db) if u.id in wanted_usual_ids]
    logger.info(
        "Checklist push %s: session_id=%s force=%s need_it_rows=%d usuals=%d",
        push_id, session_id, force, len(to_push), len(due_usuals),
    )

    progress_tracker.start(progress_token, [])
    progress_tracker.set_stage(progress_token, "reading")
    try:
        anylist_items = anylist_client.get_items()  # AnyListError -> 502, before anything changes
    except Exception as exc:
        # The push never reached the write stage: no history row is written, so without this the
        # only trace was a generic 502 line with no push_id to correlate it with.
        logger.error(
            "Checklist push %s: session_id=%s could not read the AnyList list; nothing was written "
            "(%s: %s)", push_id, session_id, type(exc).__name__, exc,
        )
        raise

    # Step names are row keys (two lines can share a display name); labels are what is shown.
    row_key = {ci.id: f"item:{ci.id}" for ci in to_push}
    wording = checklist_display.WordingIndex.build(db)
    push_items: list[PushItem] = []
    for ci in to_push:
        matches = _matches(ci.ingredient_name, anylist_items)
        best = _best_match(matches)
        actives = [m for m in matches if not m.checked]
        if len(actives) > 1:
            logger.warning(
                "Checklist push %s: %r matches %d ACTIVE AnyList items (%s) — writing to the first",
                push_id, ci.ingredient_name, len(actives), [m.name for m in actives],
            )
        push_items.append(
            PushItem(
                name=_push_name(db, ci, wording),
                quantity=_anylist_quantity(ci),
                existing_id=best.identifier if best else None,
                # 2026-09-10 hand-testing: a checklist note ("to taste", an overage hint, a
                # needs_review breakdown) was silently dropped on push; it goes to AnyList's
                # details field (plus the pack breakdown, see `_anylist_note`).
                note=_anylist_note(ci),
                key=row_key[ci.id],
            )
        )
    usual_key: dict[int, str] = {}
    usual_covered: dict[int, str] = {}  # usual id -> key of the ingredient line that already covers it
    for u in due_usuals:
        covering = next((ci for ci in to_push if _names_match(ci.ingredient_name, u.name)), None)
        if covering is not None:
            # The same item is already being pushed as an ingredient line: pushing the usual too
            # would put it on the list twice. It is reported as covered, not written.
            usual_covered[u.id] = row_key[covering.id]
            usual_key[u.id] = f"usual:{u.id}"
            logger.info(
                "Checklist push %s: usual %r is already covered by ingredient line %r",
                push_id, u.name, covering.ingredient_name,
            )
            continue
        best = _best_match(_matches(u.name, anylist_items))
        pi = PushItem(
            name=text_normalize.title_case_name(checklist_display.display_name(db, u.name, None, None, wording)),
            quantity=None,
            existing_id=best.identifier if best else None, key=f"usual:{u.id}",
        )
        usual_key[u.id] = pi.key
        push_items.append(pi)

    progress_tracker.start(
        progress_token, [p.ref for p in push_items], labels={p.ref: p.name for p in push_items}
    )
    progress_tracker.set_stage(progress_token, "reading")

    def _on_item(ref: str, status: str) -> None:
        if status == "active":
            progress_tracker.step_active(progress_token, ref)
        elif status == "done":
            progress_tracker.step_done(progress_token, ref)
        elif status == "failed":
            progress_tracker.step_failed(progress_token, ref)

    try:
        result = anylist_client.add_or_increment_items(  # AnyListError (list read) -> 502
            push_items,
            on_item=_on_item,
            on_stage=lambda stage: progress_tracker.set_stage(progress_token, stage),
            push_id=push_id,
        )
    except Exception as exc:
        # Some lines may already have been written when this fires; the push_id ties this record
        # to the per-operation lines the connector logged under the same id.
        logger.error(
            "Checklist push %s: session_id=%s failed part-way with %d line(s) attempted — AnyList "
            "may be partly updated (%s: %s)",
            push_id, session_id, len(push_items), type(exc).__name__, exc, exc_info=True,
        )
        raise
    for u in due_usuals:  # usuals folded into an ingredient line share that line's fate
        if u.id in usual_covered:
            line = next((r for r in result.items if r.key == usual_covered[u.id]), None)
            ok = line is not None and line.ok
            result.items.append(PushItemResult(
                key=usual_key[u.id],
                name=text_normalize.title_case_name(checklist_display.display_name(db, u.name, None, None, wording)),
                outcome=OUTCOME_ACTIVE if ok else OUTCOME_FAILED, intended=OUTCOME_ACTIVE,
                reason=("covered by the ingredient line" if ok else (line.reason if line else "not pushed")),
                ident=line.ident if ok else None,
            ))
    by_key = {r.key: r for r in result.items}
    for key, r in by_key.items():  # the confirm read-back is the truth, not the send
        if not r.ok:
            progress_tracker.step_failed(progress_token, key, r.reason)
    progress_tracker.set_stage(progress_token, "done" if result.confirmed else "needs-attention")

    # Write each landed line's AnyList id back onto its row, keyed by row (never by name), so the
    # next push — and the next load — find it without relying on a name match.
    for ci in to_push:
        r = by_key.get(row_key[ci.id])
        if r is not None and r.ok and r.ident:
            ci.already_on_anylist = True
            ci.anylist_item_id = r.ident

    # Belt and braces: warn (loudly, with the push_id) about any pushed line that now has more
    # than one ACTIVE match on the list — a duplicate, whoever made it.
    for ci in to_push:
        n_active = sum(
            1 for m in _matches(ci.ingredient_name, result.after_items) if not m.checked
        )
        if n_active > 1:
            logger.warning(
                "Checklist push %s: DUPLICATE — %r now has %d active items on the list",
                push_id, ci.ingredient_name, n_active,
            )

    ok_usuals = [u for u in due_usuals if usual_key[u.id] in by_key and by_key[usual_key[u.id]].ok]
    pushed_at = utcnow()
    if result.confirmed:
        session.status = "pushed"
        session.pushed_at = pushed_at
    if ok_usuals:
        usuals_service.mark_added(db, [u.id for u in ok_usuals], when=pushed_at)

    ingredient_results = [r for r in result.items if r.key.startswith("item:")]

    snapshot = {
        "push_id": push_id,
        "ingredients": [
            {"name": p.name, "quantity": p.quantity, "existing": p.existing_id is not None}
            for p in push_items
        ],
        "confirmed": result.confirmed,
        "discrepancies": result.discrepancies,
    }
    history = ShoppingHistory(
        session_id=session_id,
        pushed_at=pushed_at,
        items_json=json.dumps(snapshot),
        anylist_response_json=json.dumps(
            {
                "push_id": push_id,
                "raw": result.raw_response,
                "discrepancies": result.discrepancies,
                "items": [r.as_dict() for r in result.items],
                "timings": result.timings,
                "retried": result.retried,
            }
        ),
    )
    db.add(history)
    try:
        db.commit()
    except Exception:
        # The lines HAVE landed on AnyList but our record of the push was not saved — the one
        # state a re-push could make worse (duplicates), so it must be unmistakable in the log.
        logger.error(
            "Checklist push %s: session_id=%s items were written to AnyList (confirmed=%s) but "
            "saving the push history FAILED — do not re-push without checking the list",
            push_id, session_id, result.confirmed, exc_info=True,
        )
        raise
    db.refresh(history)

    logger.info(
        "Checklist push %s: session_id=%s added=%d updated=%d (un-crossed=%d) already_active=%d "
        "failed=%d usuals=%d confirmed=%s timings=%s",
        push_id, session_id, len(result.added), len(result.updated), len(result.uncrossed),
        len(result.already_active), len(result.failed), len(ok_usuals), result.confirmed,
        result.timings,
    )
    return {
        "session_id": session_id,
        "push_id": push_id,
        # name lists for ingredient lines only (a usual is reported under usuals_added)
        "added": [r.name for r in ingredient_results if r.outcome == "added"],
        "updated": [r.name for r in ingredient_results if r.outcome in ("updated", "un-crossed")],
        "uncrossed": [r.name for r in ingredient_results if r.outcome == "un-crossed"],
        "already_active": [r.name for r in ingredient_results if r.outcome == "already-active"],
        "failed": result.failed,
        "usuals_added": [u.name for u in ok_usuals],
        "items": [r.as_dict() for r in result.items],
        "confirmed": result.confirmed,
        "discrepancies": result.discrepancies,
        "session_status": session.status,
        "history_id": history.id,
    }

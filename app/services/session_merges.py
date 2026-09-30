"""Session-scoped ingredient overrides (Fix 3, F3.1 — see CLAUDE.md > Deferred Decisions >
checklist-time merge and > Data Model > session_ingredient_merges).

The session-only counterpart to a durable Settings row: "apply this edit for this session's
shopping list only" rather than a permanent household preference. One table,
`session_ingredient_merges`, holds every kind of "this list only" edit the Checklist
ingredient panel makes (2026-09-30, chunk 7.5), discriminated by `kind`:

  * ``merge``       (original, Fix 3) — fold `member_name` into `canonical_name`, the same
                     shape as an `ingredient_aliases` row. Written by the checklist Merge
                     chip; `remember=True` there writes a real `ingredient_aliases` row
                     instead (`services/checklist.py::merge_items()`).
  * ``substitute``  — an ad-hoc ingredient swap, moved here from the now-deleted Review
                     screen's client-held `overrides` list. Same shape as `merge` (it's a
                     rename with an optional equivalence pair); `remember=True` writes a
                     `remembered_substitutions` quick-pick instead (never bakes into the
                     recipe — see the panel endpoint's own docstring for why).
  * ``pack_size``   — a "this list only" pack size; uses `purchase_label`/`purchase_qty`/
                     `purchase_unit` instead of the rename/pair columns. `remember=True`
                     writes a real `product_units` row instead.
  * ``coarse``      — a "this list only" coarse-ingredient marking; uses `purchase_label`
                     (optional) + `recipes_per_pack`. `remember=True` writes a real
                     `coarse_ingredients` row instead.

`merge`/`substitute` reuse `ingredient_aliases.AliasResolution` as their map value (a session
merge or substitute IS an alias resolution, just scoped to one session — `merge`'s map is
consumed exactly where an alias resolution would be, in `session_consolidation.py`).
`pack_size`/`coarse` get their own small local dataclasses below, since their shape doesn't
fit the rename/pair pattern at all.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.planning import SessionIngredientMerge
from app.services.ingredient_aliases import AliasResolution

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackSizeOverride:
    """What `session_pack_override_map` hands the consolidation orchestrator for one
    ingredient — the same 3 fields a `ProductUnit` row carries, so it can be injected
    alongside real `ProductUnit` rows into `session_pack_resolution.pack_options_for()`
    without a schema-shaped adapter."""

    purchase_label: str
    purchase_qty: float
    purchase_unit: str | None = None


@dataclass(frozen=True)
class CoarseOverride:
    """What `session_coarse_override_map` hands the consolidation orchestrator for one
    ingredient — the same 2 fields a `CoarseIngredient` row carries that `_coarse_items()`
    actually reads (`purchase_label`/`recipes_per_pack`)."""

    recipes_per_pack: int
    purchase_label: str | None = None


def _map(db: Session, session_id: int, kind: str) -> list[SessionIngredientMerge]:
    return (
        db.query(SessionIngredientMerge)
        .filter(
            SessionIngredientMerge.session_id == session_id,
            SessionIngredientMerge.kind == kind,
        )
        .all()
    )


def session_merge_map(db: Session, session_id: int) -> dict[str, AliasResolution]:
    """kind='merge' rows for one session, as {member_name: AliasResolution} — loaded once per
    consolidate, same convention as `ingredient_aliases.alias_map()`."""
    return {
        row.member_name: AliasResolution(
            canonical_name=row.canonical_name,
            alias_qty=row.alias_qty,
            alias_unit=row.alias_unit,
            canonical_qty=row.canonical_qty,
            canonical_unit=row.canonical_unit,
        )
        for row in _map(db, session_id, "merge")
    }


def session_substitute_map(db: Session, session_id: int) -> dict[str, AliasResolution]:
    """kind='substitute' rows for one session, as {member_name: AliasResolution}. Replaces
    the old client-held `overrides` list `ConsolidateRequest` used to carry — read here
    instead, server-side, so it applies uniformly regardless of what triggered consolidation
    (checklist load, a pack-size save, a merge) and survives a page reload."""
    return {
        row.member_name: AliasResolution(
            canonical_name=row.canonical_name,
            alias_qty=row.alias_qty,
            alias_unit=row.alias_unit,
            canonical_qty=row.canonical_qty,
            canonical_unit=row.canonical_unit,
        )
        for row in _map(db, session_id, "substitute")
    }


def session_pack_override_map(db: Session, session_id: int) -> dict[str, PackSizeOverride]:
    """kind='pack_size' rows for one session, as {member_name: PackSizeOverride}."""
    return {
        row.member_name: PackSizeOverride(
            purchase_label=row.purchase_label,
            purchase_qty=row.purchase_qty,
            purchase_unit=row.purchase_unit,
        )
        for row in _map(db, session_id, "pack_size")
    }


def session_coarse_override_map(db: Session, session_id: int) -> dict[str, CoarseOverride]:
    """kind='coarse' rows for one session, as {member_name: CoarseOverride}."""
    return {
        row.member_name: CoarseOverride(
            recipes_per_pack=int(row.recipes_per_pack),
            purchase_label=row.purchase_label,
        )
        for row in _map(db, session_id, "coarse")
    }


def _upsert(
    db: Session, session_id: int, member_name: str, kind: str, **fields
) -> SessionIngredientMerge:
    """Upsert by (session_id, member_name, kind) — adding a second override of the SAME kind
    for the same member re-points/replaces it rather than duplicating, same convention as
    `ingredient_aliases.create_alias()`'s own re-pointing behaviour. Different kinds for the
    same member_name are independent rows (a session could, in principle, hold both a
    pack_size and a coarse override for one ingredient, though the UI never offers both at
    once — coarse skips quantity math entirely, making a pack size moot alongside it)."""
    row = (
        db.query(SessionIngredientMerge)
        .filter(
            SessionIngredientMerge.session_id == session_id,
            SessionIngredientMerge.member_name == member_name,
            SessionIngredientMerge.kind == kind,
        )
        .first()
    )
    if row is None:
        row = SessionIngredientMerge(session_id=session_id, member_name=member_name, kind=kind)
        db.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def add_session_merge(
    db: Session,
    session_id: int,
    member_name: str,
    canonical_name: str,
    *,
    alias_qty: float | None = None,
    alias_unit: str | None = None,
    canonical_qty: float | None = None,
    canonical_unit: str | None = None,
) -> SessionIngredientMerge:
    """kind='merge' — names are expected already-normalised by the caller (the checklist
    merge endpoint works from already-consolidated `ingredient_name` values)."""
    row = _upsert(
        db, session_id, member_name, "merge",
        canonical_name=canonical_name, alias_qty=alias_qty, alias_unit=alias_unit,
        canonical_qty=canonical_qty, canonical_unit=canonical_unit,
    )
    logger.info(
        "Session merge added: session_id=%s %r -> %r", session_id, member_name, canonical_name
    )
    return row


def add_session_substitute(
    db: Session,
    session_id: int,
    member_name: str,
    canonical_name: str,
    *,
    alias_qty: float | None = None,
    alias_unit: str | None = None,
    canonical_qty: float | None = None,
    canonical_unit: str | None = None,
) -> SessionIngredientMerge:
    """kind='substitute' — the "this list only" ad-hoc swap. `member_name` is the original
    ingredient's already-normalised name; `canonical_name` is the substitute."""
    row = _upsert(
        db, session_id, member_name, "substitute",
        canonical_name=canonical_name, alias_qty=alias_qty, alias_unit=alias_unit,
        canonical_qty=canonical_qty, canonical_unit=canonical_unit,
    )
    logger.info(
        "Session substitute added: session_id=%s %r -> %r", session_id, member_name, canonical_name
    )
    return row


def add_session_pack_override(
    db: Session,
    session_id: int,
    member_name: str,
    purchase_label: str,
    purchase_qty: float,
    purchase_unit: str | None = None,
) -> SessionIngredientMerge:
    """kind='pack_size' — a "this list only" pack size, resolved alongside real `ProductUnit`
    rows in `session_pack_resolution.pack_options_for()` without being written there."""
    row = _upsert(
        db, session_id, member_name, "pack_size",
        purchase_label=purchase_label, purchase_qty=purchase_qty, purchase_unit=purchase_unit,
    )
    logger.info(
        "Session pack-size override added: session_id=%s %r -> %s %s %r",
        session_id, member_name, purchase_qty, purchase_unit, purchase_label,
    )
    return row


def add_session_coarse_override(
    db: Session,
    session_id: int,
    member_name: str,
    recipes_per_pack: int,
    purchase_label: str | None = None,
) -> SessionIngredientMerge:
    """kind='coarse' — a "this list only" coarse-ingredient marking."""
    row = _upsert(
        db, session_id, member_name, "coarse",
        recipes_per_pack=recipes_per_pack, purchase_label=purchase_label,
    )
    logger.info(
        "Session coarse override added: session_id=%s %r (recipes_per_pack=%s)",
        session_id, member_name, recipes_per_pack,
    )
    return row


def clear_session_merges(db: Session, session_id: int) -> None:
    """Remove every session-scoped override for one session, any kind — basic CRUD
    completeness (every other reference table in this app has a delete path); no UI calls
    this yet, but a table with no way to undo an entry at all would be an inconsistent,
    half-built surface."""
    (
        db.query(SessionIngredientMerge)
        .filter(SessionIngredientMerge.session_id == session_id)
        .delete()
    )
    db.commit()
    logger.info("Session ingredient overrides cleared: session_id=%s", session_id)

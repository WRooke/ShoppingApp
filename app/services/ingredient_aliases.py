""""Same shopping item" ingredient aliases (2026-09-10 — see CLAUDE.md > Ingredient Aliases).

Generalised from hand-testing feedback specifically about oil ("canola oil" / "vegetable oil"
/ "oil spray" reading as separate shopping-list lines) into a plain, reusable mechanism: any
number of ``alias_name`` rows can point at one ``canonical_name``, and every ingredient name
gets folded through this map once at consolidation time
(``services/session_consolidation.py``), before grouping. Nothing here is oil-specific.

**Distinct from ``services/substitutions.py``** — read CLAUDE.md > Ingredient Aliases before
touching either file if the distinction isn't obvious from the names alone:
  * A substitution is a deliberate, per-recipe, user-confirmed swap of one product for a
    genuinely different one ("bulgarian feta" -> "regular feta") — recorded on the specific
    ``recipe_ingredients`` row, reversible per recipe, never silent.
  * An alias is "these names refer to the same thing" — no swap, no per-recipe record, no
    confirmation. It's pure relabelling, resolved fresh every time, so it benefits every
    recipe (existing and future) uniformly and automatically.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import IngredientAlias
from app.schemas.ingredient_aliases import IngredientAliasCreate, IngredientAliasUpdate

logger = logging.getLogger(__name__)

_MAX_FLATTEN_HOPS = 10  # defensive only — create_alias/update_alias never leave a chain behind


class IngredientAliasNotFoundError(Exception):
    def __init__(self, alias_id: int) -> None:
        self.alias_id = alias_id
        super().__init__(f"Ingredient alias {alias_id} not found")


class DuplicateIngredientAliasError(Exception):
    def __init__(self, alias_name: str) -> None:
        self.alias_name = alias_name
        super().__init__(f"{alias_name!r} is already grouped under another name")


class InvalidIngredientAliasError(Exception):
    """e.g. an ingredient aliased to itself."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _normalise(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _flatten(db: Session, canonical_name: str, *, exclude_id: int | None = None) -> str:
    """Follow ``canonical_name`` through any existing alias rows to its final target, so a
    newly-created row never itself points at something that's actually an alias — e.g.
    aliasing "oil spray" to "canola oil" when "canola oil" is already aliased to "vegetable
    oil" quietly stores "oil spray" -> "vegetable oil" instead of a 2-hop chain. This is what
    lets ``resolve``/``alias_map`` stay a single dict lookup with no chain-following of their
    own. The hop cap is defensive only: create_alias/update_alias always flatten on write, so
    a real cycle should never exist — this just guarantees the function still terminates if
    one somehow does.

    ``exclude_id`` — passed by ``update_alias`` for the row being updated, so re-pointing a
    row at its own ``alias_name`` (a plain self-alias) doesn't accidentally "flatten" through
    that same row and resolve to something else entirely; the self-alias check in the caller
    needs to see the raw, unresolved name in that case."""
    current = canonical_name
    seen: set[str] = set()
    for _ in range(_MAX_FLATTEN_HOPS):
        if current in seen:
            break
        seen.add(current)
        query = db.query(IngredientAlias).filter(IngredientAlias.alias_name == current)
        if exclude_id is not None:
            query = query.filter(IngredientAlias.id != exclude_id)
        row = query.first()
        if row is None:
            return current
        current = row.canonical_name
    return current


def create_alias(db: Session, data: IngredientAliasCreate) -> IngredientAlias:
    """Add one ``alias_name -> canonical_name`` mapping. ``canonical_name`` is flattened to
    its final target first (see ``_flatten``); any existing rows that were pointing at
    ``alias_name`` as *their* canonical target are re-pointed at the same final target too, so
    the whole table stays flat, not just the new row. Raises InvalidIngredientAliasError for a
    self-alias, DuplicateIngredientAliasError if ``alias_name`` is already grouped."""
    alias = _normalise(data.alias_name)
    canonical = _flatten(db, _normalise(data.canonical_name))
    if alias == canonical:
        raise InvalidIngredientAliasError("An ingredient can't be an alias for itself.")

    row = IngredientAlias(alias_name=alias, canonical_name=canonical)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateIngredientAliasError(alias) from None
    db.refresh(row)

    repointed = (
        db.query(IngredientAlias)
        .filter(IngredientAlias.canonical_name == alias, IngredientAlias.id != row.id)
        .all()
    )
    for r in repointed:
        r.canonical_name = canonical
    if repointed:
        db.commit()

    logger.info(
        "Ingredient alias added: id=%s %r -> %r (%d existing row(s) re-pointed)",
        row.id, alias, canonical, len(repointed),
    )
    return row


def get_alias(db: Session, alias_id: int) -> IngredientAlias:
    row = db.get(IngredientAlias, alias_id)
    if row is None:
        raise IngredientAliasNotFoundError(alias_id)
    return row


def list_aliases(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[IngredientAlias], int]:
    """(page, total), ordered by canonical name then alias name — so the Settings UI can
    render groups (all aliases sharing a canonical target, together) for free, same trick as
    ``substitutions.list_substitutions``'s ordering."""
    query = db.query(IngredientAlias)
    total = query.count()
    rows = (
        query.order_by(IngredientAlias.canonical_name.asc(), IngredientAlias.alias_name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def update_alias(db: Session, alias_id: int, data: IngredientAliasUpdate) -> IngredientAlias:
    """Re-group an existing alias under a different canonical name. ``alias_name`` itself is
    not editable (delete + recreate — same convention as RememberedSubstitution's immutable
    `original_name`)."""
    row = get_alias(db, alias_id)
    changes = data.model_dump(exclude_unset=True)
    if "canonical_name" in changes and changes["canonical_name"] is not None:
        new_canonical = _flatten(db, _normalise(changes["canonical_name"]), exclude_id=row.id)
        if new_canonical == row.alias_name:
            raise InvalidIngredientAliasError("An ingredient can't be an alias for itself.")
        row.canonical_name = new_canonical
    db.commit()
    db.refresh(row)
    logger.info("Ingredient alias updated: id=%s -> %r", alias_id, row.canonical_name)
    return row


def delete_alias(db: Session, alias_id: int) -> None:
    """Removing an alias only stops that one mapping — never touches recipe data (there is
    none to touch; resolution is dynamic, not written anywhere) or any other alias row."""
    row = get_alias(db, alias_id)
    db.delete(row)
    db.commit()
    logger.info("Ingredient alias deleted: id=%s", alias_id)


def alias_map(db: Session) -> dict[str, str]:
    """The whole table as {alias_name: canonical_name} — loaded once per consolidate (same
    bulk-load pattern as ``session_consolidation``'s ``staple_names``) rather than a query per
    ingredient line. See CLAUDE.md > Ingredient Aliases > Where it applies."""
    return {row.alias_name: row.canonical_name for row in db.query(IngredientAlias).all()}

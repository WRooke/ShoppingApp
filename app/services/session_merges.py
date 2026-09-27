"""Session-scoped ingredient merges (Fix 3, F3.1 — see CLAUDE.md > Deferred Decisions >
checklist-time merge and > Data Model > session_ingredient_merges).

The session-only counterpart to `services/ingredient_aliases.py`: "fold these two checklist
items into one, for this session only" rather than a durable household preference. Deliberately
mirrors that module's own shape (`AliasResolution`, `alias_map()`-style bulk load) so
`services/checklist.py::merge_items()` and `session_consolidation.py::_apply_session_merge()`
can treat a session merge exactly like an alias resolution wherever the two overlap.

Built as the reusable precedent for `HANDOVER-review-checklist-merge.md`'s still-open
"override persistence across page loads" question (same table shape, same
bulk-load-once-per-consolidate convention) — this module does not implement that separate,
undecided proposal, just avoids painting it into a corner.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.planning import SessionIngredientMerge
from app.services.ingredient_aliases import AliasResolution

logger = logging.getLogger(__name__)


def session_merge_map(db: Session, session_id: int) -> dict[str, AliasResolution]:
    """The whole table for one session as {member_name: AliasResolution} — loaded once per
    consolidate, same convention as `ingredient_aliases.alias_map()`. Reuses that module's own
    `AliasResolution` shape directly rather than a bespoke dataclass, since a session merge is
    resolved by `session_consolidation.py::_apply_session_merge()` exactly the way an alias
    resolution is."""
    return {
        row.member_name: AliasResolution(
            canonical_name=row.canonical_name,
            alias_qty=row.alias_qty,
            alias_unit=row.alias_unit,
            canonical_qty=row.canonical_qty,
            canonical_unit=row.canonical_unit,
        )
        for row in db.query(SessionIngredientMerge).filter(
            SessionIngredientMerge.session_id == session_id
        )
    }


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
    """Upsert by (session_id, member_name) — same "adding a second merge for the same member
    re-points it rather than duplicating" convention as `ingredient_aliases.create_alias()`'s
    own re-pointing behaviour. Names are expected already-normalised by the caller (the
    checklist merge endpoint works from already-consolidated `ingredient_name` values)."""
    row = (
        db.query(SessionIngredientMerge)
        .filter(
            SessionIngredientMerge.session_id == session_id,
            SessionIngredientMerge.member_name == member_name,
        )
        .first()
    )
    if row is None:
        row = SessionIngredientMerge(session_id=session_id, member_name=member_name)
        db.add(row)
    row.canonical_name = canonical_name
    row.alias_qty = alias_qty
    row.alias_unit = alias_unit
    row.canonical_qty = canonical_qty
    row.canonical_unit = canonical_unit
    db.commit()
    db.refresh(row)
    logger.info(
        "Session ingredient merge added: session_id=%s %r -> %r",
        session_id, member_name, canonical_name,
    )
    return row


def clear_session_merges(db: Session, session_id: int) -> None:
    """Remove every merge for one session — basic CRUD completeness (every other reference
    table in this app has a delete path); no UI calls this yet, but a merges table with no way
    to undo a merge at all would be an inconsistent, half-built surface."""
    (
        db.query(SessionIngredientMerge)
        .filter(SessionIngredientMerge.session_id == session_id)
        .delete()
    )
    db.commit()
    logger.info("Session ingredient merges cleared: session_id=%s", session_id)

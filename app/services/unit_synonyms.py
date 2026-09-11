"""Unit-spelling canonicalisation (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling >
Layer A). Fixes the actual bug hand-testing surfaced: "clove" and "cloves", or "g" and
"grams", were treated as genuinely different units and landed in different, unmergeable
consolidation buckets — not a vocabulary-restriction problem, a plain reconciliation bug.

Two complementary pieces, deliberately kept separate:
  * ``strip_plural()`` — a generic, tableless heuristic (same idea as
    ``checklist.py._singularise()``, applied to unit strings) that handles the common
    discrete-unit plural case (clove/cloves, bunch/bunches, sprig/sprigs) for free, no
    Settings entry needed.
  * ``unit_synonyms`` (this table) — genuine word-form differences the strip rule can't
    derive on its own (gram(s) -> g, tablespoon(s)/tbs -> tbsp). Small, one-time, universal
    seed (not per-ingredient — see CLAUDE.md), Settings-editable for any gap.

Resolved **dynamically** at consolidation time (``services/session_consolidation.py``), same
architectural point and reasoning as ``ingredient_aliases`` — a synonym added later should
retroactively fix recipes saved before it existed, which a save-time rewrite couldn't do.

Also home to Layer B (``known_units_for_ingredient()``) — "what units has this ingredient
been used with before", derived live from ``recipe_ingredients`` with **zero new table and
zero admin**: it's a plain query, pooled across an ingredient's ``ingredient_aliases`` group
so typing "vegetable oil" also surfaces units seen under "canola oil". Kept in this module
(despite querying ``recipe_ingredients``, conceptually ``services/recipes.py``'s domain)
because it's fundamentally a "what units..." question and needs ``resolve_unit()`` to
de-duplicate its results anyway — putting it here keeps the unit theme in one place rather
than pushing `recipes.py` past the file-size guideline for a query that's arguably more
about units than about recipes.

``learn_new_units()`` (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling > Admin
reduction) closes the loop on the remaining manual admin for this table: a genuinely
never-before-seen unit spelling gets one on-demand classification call
(``ai_extraction.classify_units()``) asking only whether it's a same-magnitude variant of a
standard unit; a confident match writes a normal row here automatically. Called from
``services/recipes.py`` after an ingredient save, never blocking it on failure.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py.
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import UnitSynonym
from app.models.recipes import RecipeIngredient
from app.schemas.unit_synonyms import UnitSynonymCreate, UnitSynonymUpdate
from app.services import ingredient_aliases
from app.services.scaling import NO_SCALE_UNITS

logger = logging.getLogger(__name__)

# The standard units classify_units() (app/services/ai_extraction.py) is allowed to match a
# spelling against. Kept here too (not just re-exported from ai_extraction) so this module's
# own "already resolves to a standard unit, nothing to learn" check doesn't need to import
# the AI module just for a constant.
_STANDARD_UNITS = frozenset({"g", "kg", "ml", "l", "tsp", "tbsp", "cup"})

# Endings a plain "+s"/"+es" plural typically adds to a short discrete-unit noun. Deliberately
# conservative — a false strip (treating a genuinely different word as a plural of another)
# is worse than missing one, since a miss just falls through to being treated as its own unit
# (the pre-existing, safe default), same reasoning as checklist.py's _singularise().
def strip_plural(unit: str) -> str:
    """"cloves" -> "clove", "bunches" -> "bunch", "boxes" -> "box". Leaves anything
    ambiguous or already-singular-looking alone. Runs BEFORE the ``unit_synonyms`` lookup, so
    that table only needs entries for genuine word-form differences, not plain plurals."""
    u = unit.strip().lower()
    if len(u) > 4 and u.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return u[:-2]
    if len(u) > 3 and u.endswith("s") and not u.endswith("ss"):
        return u[:-1]
    return u


class UnitSynonymNotFoundError(Exception):
    def __init__(self, synonym_id: int) -> None:
        self.synonym_id = synonym_id
        super().__init__(f"Unit synonym {synonym_id} not found")


class DuplicateUnitSynonymError(Exception):
    def __init__(self, alias_unit: str) -> None:
        self.alias_unit = alias_unit
        super().__init__(f"{alias_unit!r} is already mapped to another unit")


class InvalidUnitSynonymError(Exception):
    """e.g. a unit mapped to itself."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _normalise(unit: str) -> str:
    return strip_plural(unit)


def create_synonym(db: Session, data: UnitSynonymCreate) -> UnitSynonym:
    """Add one ``alias_unit -> canonical_unit`` mapping. Both sides are run through
    ``strip_plural()`` first, so a plural typed on either side still lands correctly. Raises
    InvalidUnitSynonymError for a self-mapping, DuplicateUnitSynonymError if `alias_unit` is
    already mapped."""
    alias = _normalise(data.alias_unit)
    canonical = _normalise(data.canonical_unit)
    if alias == canonical:
        raise InvalidUnitSynonymError("A unit can't be a synonym for itself.")

    row = UnitSynonym(alias_unit=alias, canonical_unit=canonical)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateUnitSynonymError(alias) from None
    db.refresh(row)
    logger.info("Unit synonym added: id=%s %r -> %r", row.id, alias, canonical)
    return row


def get_synonym(db: Session, synonym_id: int) -> UnitSynonym:
    row = db.get(UnitSynonym, synonym_id)
    if row is None:
        raise UnitSynonymNotFoundError(synonym_id)
    return row


def list_synonyms(
    db: Session, *, limit: int = 200, offset: int = 0
) -> tuple[list[UnitSynonym], int]:
    query = db.query(UnitSynonym)
    total = query.count()
    rows = (
        query.order_by(UnitSynonym.canonical_unit.asc(), UnitSynonym.alias_unit.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def update_synonym(db: Session, synonym_id: int, data: UnitSynonymUpdate) -> UnitSynonym:
    """Re-point an existing synonym at a different canonical unit. `alias_unit` itself is not
    editable (delete + recreate)."""
    row = get_synonym(db, synonym_id)
    changes = data.model_dump(exclude_unset=True)
    if "canonical_unit" in changes and changes["canonical_unit"] is not None:
        new_canonical = _normalise(changes["canonical_unit"])
        if new_canonical == row.alias_unit:
            raise InvalidUnitSynonymError("A unit can't be a synonym for itself.")
        row.canonical_unit = new_canonical
    db.commit()
    db.refresh(row)
    logger.info("Unit synonym updated: id=%s -> %r", synonym_id, row.canonical_unit)
    return row


def delete_synonym(db: Session, synonym_id: int) -> None:
    row = get_synonym(db, synonym_id)
    db.delete(row)
    db.commit()
    logger.info("Unit synonym deleted: id=%s", synonym_id)


def synonym_map(db: Session) -> dict[str, str]:
    """The whole table as {alias_unit: canonical_unit} — loaded once per consolidate (same
    bulk-load pattern as ``ingredient_aliases.alias_map``) rather than a query per line."""
    return {row.alias_unit: row.canonical_unit for row in db.query(UnitSynonym).all()}


def resolve_unit(unit: str | None, synonyms: dict[str, str]) -> str | None:
    """The canonical spelling for a unit string: strip a plain plural, then look up any
    remaining word-form synonym. `None` (a bare count, no unit) passes through unchanged —
    there's nothing to canonicalise. Used by ``session_consolidation.py`` at the same layer
    ingredient alias resolution runs, applied to a line's unit rather than its name."""
    if unit is None:
        return None
    stripped = strip_plural(unit)
    return synonyms.get(stripped, stripped)


# --- Layer B: per-ingredient known units, derived live (2026-09-12) --------------------


def _alias_group_names(db: Session, name: str) -> set[str]:
    """Every ingredient name that should count as "the same ingredient" for pooling known
    units — the given name plus its whole ``ingredient_aliases`` group, whichever direction
    it points (an alias asking about its own canonical, or a canonical asking about its
    aliases)."""
    normalised = " ".join(name.strip().lower().split())
    amap = ingredient_aliases.alias_map(db)
    canonical = amap[normalised].canonical_name if normalised in amap else normalised
    group = {canonical}
    group.update(alias for alias, res in amap.items() if res.canonical_name == canonical)
    return group


def known_units_for_ingredient(db: Session, name: str) -> list[str]:
    """Units already used for this ingredient (pooled across its alias group), most-
    frequently-used first, each already canonicalised through ``resolve_unit`` — so "grams"
    and "g" already show up as one entry, "g", not two. Zero admin: a plain query over
    ``recipe_ingredients``, no new table (CLAUDE.md > Ingredient Unit Handling > Layer B).
    Surfaced as quick-pick buttons on the unit input in manual entry / editing / capture
    review, and as the comparison set for the Layer C duplicate-unit nudge."""
    names = _alias_group_names(db, name)
    if not names:
        return []
    synonyms = synonym_map(db)
    rows = (
        db.query(RecipeIngredient.unit, func.count(RecipeIngredient.id))
        .filter(RecipeIngredient.name.in_(names), RecipeIngredient.unit.isnot(None))
        .group_by(RecipeIngredient.unit)
        .all()
    )
    counts: dict[str, int] = {}
    for unit, count in rows:
        canonical = resolve_unit(unit, synonyms)
        if canonical:
            counts[canonical] = counts.get(canonical, 0) + count
    return sorted(counts, key=lambda u: (-counts[u], u))


# --- Admin reduction: auto-learn new unit spellings (2026-09-12) -----------------------


def learn_new_units(
    db: Session,
    units: list[str | None],
    *,
    exclude_ingredient_ids: set[int] | None = None,
    context_id: str | None = None,
) -> None:
    """Best-effort, on-demand classification of never-before-seen unit spellings against the
    app's standard unit set — see CLAUDE.md > Ingredient Unit Handling > Admin reduction.
    Called after an ingredient save (manual entry, editing, or a capture-review edit) with
    whichever raw `unit` value(s) it introduced.

    A unit is only worth spending a classification call on when it (a) doesn't already
    resolve to a standard unit via ``strip_plural()``/the existing synonym map, AND (b) has
    never appeared as any ``recipe_ingredients.unit`` value anywhere before
    (``exclude_ingredient_ids`` excludes the row(s) just saved, so they don't count as their
    own prior use). Condition (b) is load-bearing: a real, established discrete unit
    ("clove", "bunch", "pinch", ...) only ever gets classified **once**, the first time it's
    ever typed anywhere in the app — the moment that first (correctly negative)
    classification happens it becomes an "already-used" unit like any other and is never
    asked about again, at zero further cost.

    NEVER blocks or fails the caller's save: any classification failure (disabled, quota,
    parse, network) is caught and logged here — the unit is simply left as its own distinct
    unit, exactly today's behaviour with this feature turned off.
    """
    exclude = exclude_ingredient_ids or set()
    synonyms = synonym_map(db)

    candidates: set[str] = set()
    for raw in units:
        if not raw:
            continue
        unit = raw.strip().lower()
        if not unit or unit in NO_SCALE_UNITS:
            continue
        if resolve_unit(unit, synonyms) in _STANDARD_UNITS:
            continue  # already resolves to a standard unit -- nothing to learn
        candidates.add(unit)
    if not candidates:
        return

    novel: list[str] = []
    for unit in candidates:
        forms = list({unit, strip_plural(unit)})
        query = db.query(RecipeIngredient.id).filter(func.lower(RecipeIngredient.unit).in_(forms))
        if exclude:
            query = query.filter(RecipeIngredient.id.notin_(list(exclude)))
        if query.first() is None:
            novel.append(unit)
    if not novel:
        return

    # Deferred import: this is the only function in this module that talks to the network,
    # and only ai_extraction.py knows about §0c (AI_EXTRACTION_ENABLED/FAKE_MODE) -- keeping
    # the import local avoids paying for it on every ordinary ingredient save where nothing
    # novel was typed (the overwhelmingly common case).
    from app.services import ai_extraction

    try:
        matches = ai_extraction.classify_units(db, context_id=context_id, unit_texts=novel)
    except ai_extraction.AiExtractionDisabledError:
        # The expected default state (AI_EXTRACTION_ENABLED=false) — not an error, so no
        # WARNING/traceback; _require_enabled() already logged this once at that call.
        return
    except ai_extraction.AiExtractionError as exc:
        # Already logged with full detail inside _call_gemini (quota/parse/network) --
        # nothing more to add here beyond noting the unit stays unclassified.
        logger.info("learn_new_units: classification skipped for %s (%s)", novel, exc)
        return
    except Exception:  # belt-and-braces -- this must never break a recipe/ingredient save
        logger.warning("learn_new_units: unexpected failure classifying %s", novel, exc_info=True)
        return

    for alias, canonical in matches.items():
        try:
            create_synonym(db, UnitSynonymCreate(alias_unit=alias, canonical_unit=canonical))
            logger.info(
                "learn_new_units: auto-added unit synonym %r -> %r (classified, no admin needed)",
                alias, canonical,
            )
        except (DuplicateUnitSynonymError, InvalidUnitSynonymError) as exc:
            logger.info("learn_new_units: skipped %r -> %r (%s)", alias, canonical, exc)

"""Natural-English display names for the checklist (2026-09-27) — raised by hand-testing: the
checklist showed "8 chicken thigh" (grammatically the matching key, but wrong once a real
quantity or weight makes the plural the natural reading — "8 chicken thighs").

**Distinct from `text_normalize.py`'s job, on purpose.** `text_normalize.normalise_ingredient_name()`
is the internal MATCHING key and must stay singular and stable — it's what
`session_checklist_items.ingredient_name`, `product_units.ingredient_name`, and every other
reference-table lookup keys off. This module never touches that key; it only computes a
separate, ephemeral DISPLAY string, recomputed fresh on every read/push, exactly the same
"derive, don't store" precedent as `services/consolidation.py`'s `recipe_breakdown`.

**Countability is a fact about the ingredient, not the word's spelling — deliberately not
guessed from a library.** `text_normalize.pluralise()` (which this module calls) will happily
pluralise a genuine mass noun too ("flour" -> "flours"), because no general-purpose English
morphology library (checked: `inflect`'s full public API has no countability classifier;
WordNet-style resources exist but are sparse/unreliable for this and need a large corpora
download) can derive "is this word ever used as a discrete, countable thing" from its spelling
alone — it's a lexical fact about the specific word, often context-dependent even in real
English ("chicken" the meat vs. "chicken" the animal). This module uses this household's own
real usage as that signal instead: has this ingredient ever actually been recorded with a bare
count (``unit IS NULL``) anywhere in ``recipe_ingredients``? A mass noun (flour, salt, oil) is
never extracted or typed that way by this app's own conventions, so this is a reliable,
zero-admin, "derive live from real usage" signal — the same precedent as this app's other
zero-admin per-ingredient facts (`unit_synonyms.py`'s Layer B, `known_units_for_ingredient()`).
An ingredient never yet recorded as a bare count defaults to NOT pluralising — a cosmetic miss,
not a wrong merge, same safe-failure direction as everywhere else in this app.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py (none are actually raised here; this module never fails a request).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.recipes import RecipeIngredient
from app.schemas.sessions import ChecklistItemRead
from app.services import text_normalize, unit_synonyms


def is_known_countable(db: Session, name: str) -> bool:
    """Has this ingredient (pooled across its `ingredient_aliases` group) ever been recorded
    with a bare count (`unit IS NULL`) anywhere in `recipe_ingredients`? See the module
    docstring for why this — not a library — is the countability signal used here.

    Matched in Python against the *normalised* name, not a SQL ``RecipeIngredient.name.in_()``
    filter — same fix, same reason, as ``unit_synonyms.known_units_for_ingredient()``:
    ``recipe_ingredients.name`` is deliberately never rewritten through ``text_normalize`` (a
    recipe's own page always shows exactly what was extracted/typed, plural or not), so a raw
    stored name — "carrots", "eggs" — can differ in shape from the normalised group names
    `alias_group_names` returns, and a literal-equality filter silently misses every one of
    them. Caught live (2026-09-27) — a real Gemini capture stored "carrots"/"eggs", and this
    function's original SQL-filter version never flagged either as countable despite both being
    genuine count nouns with a bare-count row on record. Household-scale data, so a full
    column scan here is cheap, same precedent as the unit_synonyms.py fix it mirrors."""
    names = unit_synonyms.alias_group_names(db, name)
    if not names:
        return False
    rows = (
        db.query(RecipeIngredient.name)
        .filter(RecipeIngredient.unit.is_(None))
        .all()
    )
    return any(text_normalize.normalise_ingredient_name(row[0]) in names for row in rows)


def _is_discrete_counting_unit(unit: str | None) -> bool:
    """True for a present unit that isn't one of the standard *measured* units (g, kg, ml, L,
    tsp, tbsp, cup) — by this app's own vocabulary (``unit_synonyms.STANDARD_UNITS``), that
    means it's a discrete counting word a household or an extraction typed: "clove", "sprig",
    "head", "bunch", "pinch", "can", and so on. No fixed enum is needed here — anything outside
    the measured set already means this by construction."""
    return bool(unit) and unit.lower() not in unit_synonyms.STANDARD_UNITS


def display_name(
    db: Session, name: str, quantity: float | None, unit: str | None
) -> str:
    """The natural-English display form of an already-normalised (singular) ingredient `name`
    for one specific (quantity, unit) pair — pluralised when this ingredient is a confirmed
    count noun (`is_known_countable`) AND either the quantity isn't exactly 1 or a weight/volume
    unit is present (a household buying "500g chicken thighs" is still buying more than one
    piece, even though the amount itself is a weight, not a count). `quantity is None` (a
    `needs_review` line with nothing resolved yet, or a genuine "to taste" line) never
    pluralises — there's no concrete amount to reason a plural from, and the ingredients that
    actually hit this path (salt, pepper) are never count nouns anyway.

    2026-09-27 — never pluralises the NAME when `unit` is a discrete counting unit (see
    `_is_discrete_counting_unit`). Caught live: a real capture of "4 cloves garlic" (after the
    extraction-prompt fix for the bug below) still showed "garlics" next to "12 clove" on the
    checklist's needs-review card. In natural English a discrete counting unit is what
    pluralises ("12 cloves of garlic"), never the ingredient name itself ("garlics" is wrong at
    any quantity) — see `display_unit` below, which handles that side instead. This is a
    genuinely different case from a *measured* unit (g/ml/tsp/...), where the ingredient name
    stays the thing that naturally pluralises ("500g chicken thighs")."""
    if quantity is None:
        return name
    if quantity == 1 and unit is None:
        return name
    if not is_known_countable(db, name):
        return name
    if _is_discrete_counting_unit(unit):
        return name
    return text_normalize.pluralise(name)


def display_unit(unit: str | None, quantity: float | None) -> str | None:
    """The natural-English display form of a unit string for a given quantity — pluralises a
    discrete counting unit when the quantity isn't exactly 1 ("12 cloves", not "12 clove"), and
    leaves a standard measured unit (g, ml, tsp, ...) alone regardless of quantity ("20 ml", not
    "20 mls" — those never pluralise in this app's own usage or in real Australian shopping-list
    English). `unit=None` (a bare count) passes through unchanged; the count itself is carried
    entirely by `display_name`'s own pluralisation in that case."""
    if not unit or not _is_discrete_counting_unit(unit) or quantity == 1:
        return unit
    return text_normalize.pluralise(unit)


def decorate(db: Session, read: ChecklistItemRead) -> ChecklistItemRead:
    """Fill in `display_name` and `display_unit` (this row's own total_quantity/total_unit),
    and the same pair for each review option, on an already-validated `ChecklistItemRead`.
    Shared by both callers that build this schema from a `SessionChecklistItem` row
    (`routers/checklist.py` and `routers/sessions.py`'s consolidate endpoint) — the same lesson
    the ingredient-name-matching plan already learned once this session about not re-deriving
    the same logic in more than one place. Computed fresh every call, never persisted, same
    "ephemeral, derive don't store" precedent as `recipe_breakdown`."""
    name = read.ingredient_name
    options = [
        opt.model_copy(update={"display_unit": display_unit(opt.unit, opt.quantity)})
        for opt in read.review_options
    ]
    return read.model_copy(
        update={
            "display_name": display_name(db, name, read.total_quantity, read.total_unit),
            "display_unit": display_unit(read.total_unit, read.total_quantity),
            "review_options": options,
        }
    )

"""Display names for the checklist and for what is pushed to AnyList.

**History.** 2026-09-27: the checklist showed "8 chicken thigh" (the matching key) where a real
quantity makes the plural natural, so this module pluralised "count nouns", deciding countability
from whether the ingredient had ever been recorded with a bare count (``unit IS NULL``) anywhere
in the alias group. **2026-10-06 (Chunk 6.7) replaced that** — it produced "salts", "parmesans",
"vegetable oils" (one stray NULL-unit "salt" row, or one "oil spray" row elsewhere in the alias
group, made a whole group "countable") while leaving always-measured plural nouns singular
("black bean", "cashew nut", "corn chip", "salted peanut"). See docs/ingredient-handling.md >
"Display names" for the full rule, worked examples and the failure analysis.

**The rule now: show the household's own wording.** The name shown is the form this household's
own recipes use for that ingredient — "black beans", "salt", "olive oil", "parmesan" — chosen from
the recipes that name *that exact ingredient key* (never pooled across an alias group: pooling is
what let one "oil spray" row pluralise "vegetable oil"). Countability is no longer guessed.

**Safety property — this module can never affect matching.** The matching key
(``text_normalize.normalise_ingredient_name``, stored in ``session_checklist_items.ingredient_name``
and used by every reference table and by the AnyList name match) is untouched; this module only
derives a display string and never writes anything. Every string it returns is guaranteed to
normalise back to the same key (``_guard``: if a candidate ever would not, the key itself is
returned), so a name pushed to AnyList always matches its own checklist row on the next push, and
a re-push of an item first pushed under an older spelling ("Salts") still finds it.

**Quantity only chooses between the household's own forms; it never invents a plural.**
  * a bare count of 1 or less ("1 carrot", "0.5 onion") -> the singular key;
  * a bare count above 1 ("6 carrots") -> a plural form if the household wrote one, otherwise the
    form as written;
  * anything with a unit ("500 g black beans", "2 tbsp olive oil", "12 clove garlic") or no
    quantity ("salt, to taste") -> the household's most-used form as written.
(An earlier draft pluralised a bare count by definition. Real data killed that: recipes do contain
stray unitless amounts for mass nouns ("black pepper 2"), which produced "black peppers" and
"flours" — the very bug this module exists to remove. A plural is only ever shown if the household
wrote one.)
The single case where a plural is COMPUTED: the household never wrote the ingredient under its own
key (an alias canonical such as "canned tomato", a session substitute, a usual) AND the wording of
its alias-group members is mostly plural ("diced tomatoes", "crushed tomatoes"). Even then never for
names containing "or"/"and"/"of"/"with" or brackets, where only the last word changing would read
wrongly.

Plain Python / SQLAlchemy — no ``fastapi`` import. Exceptions translate to the envelope in
app/main.py (none are raised here; this module never fails a request).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.models.catalog import IngredientAlias
from app.models.recipes import RecipeIngredient
from app.schemas.sessions import ChecklistItemRead
from app.services import text_normalize, unit_synonyms

# Names where changing only the last word would read wrongly ("pita bread or flatbreads" must be
# left exactly as written, never "pita breads or flatbreads"), so a plural is never COMPUTED for
# them — the household's own written form is still used as-is.
_UNSAFE_TO_PLURALISE = re.compile(r"\b(or|and|of|with|per)\b|[()/&,]")


class WordingIndex:
    """How this household actually writes each ingredient, built once per request from
    ``recipe_ingredients`` (household scale: a few hundred rows) and passed around, so a checklist
    of 70 rows costs one pass, not 70.

    ``forms[key]`` counts the written forms (hyphens folded, lower-case) of recipe ingredients whose
    *effective* name — ``resolved_ingredient`` when a substitution is confirmed, else ``name``, the
    same choice consolidation makes — normalises to exactly ``key``. ``members[canonical]`` lists
    the alias names that resolve to a canonical, for the no-own-wording fallback only."""

    def __init__(
        self,
        forms: dict[str, Counter] | None = None,
        members: dict[str, list[str]] | None = None,
    ) -> None:
        self.forms: dict[str, Counter] = forms or {}
        self.members: dict[str, list[str]] = members or {}

    @classmethod
    def build(cls, db: Session | None) -> "WordingIndex":
        if db is None:
            return cls()
        forms: dict[str, Counter] = defaultdict(Counter)
        for name, resolved in db.query(RecipeIngredient.name, RecipeIngredient.resolved_ingredient).all():
            effective = resolved or name
            if not effective or not effective.strip():
                continue
            forms[text_normalize.normalise_ingredient_name(effective)][text_normalize.base_norm(effective)] += 1
        members: dict[str, list[str]] = defaultdict(list)
        for alias_name, canonical in db.query(IngredientAlias.alias_name, IngredientAlias.canonical_name).all():
            members[text_normalize.normalise_ingredient_name(canonical)].append(
                text_normalize.normalise_ingredient_name(alias_name)
            )
        return cls(dict(forms), dict(members))

    def own_forms(self, key: str) -> Counter:
        return self.forms.get(key, Counter())

    def members_mostly_plural(self, key: str) -> bool:
        """Is the household's wording for this canonical's alias MEMBERS mostly plural
        ("diced tomatoes", "crushed tomatoes" -> canned tomato)? Only a majority counts, and only
        forms actually written are considered — no countability guessing."""
        plural = total = 0
        for member in self.members.get(key, []):
            for form, n in self.own_forms(member).items():
                total += n
                plural += n if text_normalize.looks_plural(form) else 0
        return total > 0 and plural * 2 > total


def _best(forms: Counter, prefer: str | None = None) -> str | None:
    """The household's most-used form. `prefer` ('plural'/'singular') narrows to forms that look
    that way when any exist. Ties: longer form, then alphabetical (deterministic)."""
    candidates = list(forms.items())
    if prefer in ("plural", "singular") and candidates:
        want = prefer == "plural"
        narrowed = [(f, n) for f, n in candidates if text_normalize.looks_plural(f) == want]
        candidates = narrowed or candidates
    if not candidates:
        return None
    return sorted(candidates, key=lambda fn: (-fn[1], -len(fn[0]), fn[0]))[0][0]


def _guard(candidate: str, key: str) -> str:
    """The safety net behind the module's central guarantee: a display string must normalise back
    to the key it was derived from, or the key itself is used. (Always true for a form taken from
    the household's own rows, by construction; checked for computed plurals.)"""
    return candidate if text_normalize.normalise_ingredient_name(candidate) == key else key


def _key_text(key: str, forms: Counter) -> str:
    """The key as display text. Normally the key itself — but a few stored keys are not fixed
    points of `normalise` ("cheeses" -> "chees", whose own normalisation is "chee"; see
    docs/deferred-decisions.md), and showing "chees" would both look wrong and break the central
    guarantee (display normalises back to the key). Those use the household's own wording, or a
    guarded plural of the key ("chees" -> "cheeses", which does normalise back), else the key."""
    if text_normalize.normalise_ingredient_name(key) == key:
        return key
    return _best(forms) or _computed_plural(key)


def _computed_plural(key: str) -> str:
    if _UNSAFE_TO_PLURALISE.search(key):
        return key
    return _guard(text_normalize.pluralise(key), key)


def _is_discrete_counting_unit(unit: str | None) -> bool:
    """True for a present unit that isn't one of the standard *measured* units (g, kg, ml, L,
    tsp, tbsp, cup) — by this app's own vocabulary (``unit_synonyms.STANDARD_UNITS``), that
    means it's a discrete counting word a household or an extraction typed: "clove", "sprig",
    "head", "bunch", "pinch", "can", and so on. Used by `display_unit` below."""
    return bool(unit) and unit.lower() not in unit_synonyms.STANDARD_UNITS


def display_name(
    db: Session | None,
    name: str,
    quantity: float | None,
    unit: str | None,
    index: WordingIndex | None = None,
) -> str:
    """The display form of the ingredient `key` (= `name`, already normalised/singular) for one
    (quantity, unit) pair — see the module docstring for the rule and the guarantee that the
    result always normalises back to `name`. Pass a prebuilt `index` when calling in a loop."""
    key = name
    if index is None:
        index = WordingIndex.build(db)
    forms = index.own_forms(key)
    if quantity is not None and quantity <= 1 and unit is None:
        return _key_text(key, forms)  # "1 carrot", "0.5 onion"
    bare_count = quantity is not None and unit is None  # and quantity > 1, by the line above

    if forms:
        # A count of several prefers a plural form IF the household wrote one; nothing is computed.
        return _guard(_best(forms, prefer="plural" if bare_count else None) or key, key)

    # The household never wrote this ingredient under its own key.
    if index.members_mostly_plural(key):
        return _computed_plural(key)
    return _key_text(key, forms)


def display_unit(unit: str | None, quantity: float | None) -> str | None:
    """The natural-English display form of a unit string for a given quantity — pluralises a
    discrete counting unit when the quantity isn't exactly 1 ("12 cloves", not "12 clove"), and
    leaves a standard measured unit (g, ml, tsp, ...) alone regardless of quantity ("20 ml", not
    "20 mls" — those never pluralise in this app's own usage or in real Australian shopping-list
    English). `unit=None` (a bare count) passes through unchanged; the count itself is carried
    entirely by `display_name`'s own plural form in that case."""
    if not unit or not _is_discrete_counting_unit(unit) or quantity == 1:
        return unit
    return text_normalize.pluralise(unit)


def decorate(db: Session, read: ChecklistItemRead, index: WordingIndex | None = None) -> ChecklistItemRead:
    """Fill in `display_name` and `display_unit` (this row's own total_quantity/total_unit),
    and the same pair for each review option, on an already-validated `ChecklistItemRead`.
    Shared by both callers that build this schema from a `SessionChecklistItem` row
    (`routers/checklist.py` and `routers/sessions.py`'s consolidate endpoint). Computed fresh every
    call, never persisted — "derive, don't store", same as `recipe_breakdown`. Callers that decorate
    many rows pass one shared `index` (see `WordingIndex`)."""
    name = read.ingredient_name
    index = index if index is not None else WordingIndex.build(db)
    options = [
        opt.model_copy(update={"display_unit": display_unit(opt.unit, opt.quantity)})
        for opt in read.review_options
    ]
    return read.model_copy(
        update={
            "display_name": display_name(db, name, read.total_quantity, read.total_unit, index),
            "display_unit": display_unit(read.total_unit, read.total_quantity),
            "review_options": options,
        }
    )

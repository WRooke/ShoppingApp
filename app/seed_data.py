"""Starter data for the reference catalogue.

Phase 1 defines the data and an idempotent ``seed_reference_data`` helper but
does NOT call it. Wiring the seed into first-run startup is a Phase 2
deliverable (see CLAUDE.md > Build Phases > Phase 2).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.catalog import CoarseIngredient, IngredientAlias, ProductUnit, Staple, UnitSynonym

logger = logging.getLogger(__name__)

# Australian common grocery pack sizes. Marked is_preseeded=1 on insert.
#
# A few ingredients carry MORE THAN ONE pack size on purpose (eggs, milk, yoghurt) — see
# CLAUDE.md > Scaling Logic > "Multi-pack, seeded from day one". This is a deliberate small
# departure from the "don't pre-enumerate pack sizes" norm, so the several-rows purchase
# resolution path (services/purchase_units.py) is exercised in real use from the start.
# Uniqueness is (ingredient_name, purchase_label) as of Phase 4 Chunk 4.1.
PRODUCT_UNIT_SEEDS: list[dict] = [
    # Dairy & eggs
    {"ingredient_name": "eggs", "purchase_label": "half dozen", "purchase_qty": 6, "purchase_unit": "each"},
    {"ingredient_name": "eggs", "purchase_label": "dozen", "purchase_qty": 12, "purchase_unit": "each"},
    {"ingredient_name": "milk", "purchase_label": "1L bottle", "purchase_qty": 1, "purchase_unit": "L"},
    {"ingredient_name": "milk", "purchase_label": "2L bottle", "purchase_qty": 2, "purchase_unit": "L"},
    {"ingredient_name": "yoghurt", "purchase_label": "500g tub", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "yoghurt", "purchase_label": "1kg tub", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "butter", "purchase_label": "250g block", "purchase_qty": 250, "purchase_unit": "g"},
    {"ingredient_name": "cream", "purchase_label": "300ml carton", "purchase_qty": 300, "purchase_unit": "ml"},
    {"ingredient_name": "sour cream", "purchase_label": "200g tub", "purchase_qty": 200, "purchase_unit": "g"},
    # Meat
    {"ingredient_name": "beef mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "pork mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken breast", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken thigh", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "bacon", "purchase_label": "175g pack", "purchase_qty": 175, "purchase_unit": "g"},
    # Pantry
    {"ingredient_name": "plain flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "self-raising flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "white sugar", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "brown sugar", "purchase_label": "500g bag", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "basmati rice", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "pasta", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "diced tomatoes", "purchase_label": "400g can", "purchase_qty": 400, "purchase_unit": "g"},
    {"ingredient_name": "coconut cream", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "coconut milk", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "chicken stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
    {"ingredient_name": "beef stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
]

SECTION_VOCABULARY: list[str] = [
    # Canonical, fixed, store-independent section vocabulary (Shop Layout Reorganisation
    # addendum). Not a DB table — store_sections.section_name and product_sections.section_name
    # are free text, but the UI should only offer these. Starter list; confirm/adjust with the
    # household before the store setup + capture-time section-suggestion UI is built.
    "produce",
    "dairy",
    "meat & seafood",
    "bakery",
    "frozen",
    "pantry",
    "household",
    "deli",
    "drinks",
    "other",
]

# Deliberately minimal (confirmed 2026-09-05 — see CLAUDE.md > Staples Starter List). Earlier
# draft over-seeded this with anything vaguely pantry-shaped (soy sauce, vinegars, dried
# herbs/spices, tomato paste, dijon mustard, garlic) without confirming any of it actually
# matched what this household treats as "assume we have it, don't put it on the list". Add
# more here (or via Settings, once Chunk 2.5 exists) only as real recipes surface a genuine
# staple gap — do not pre-guess the rest of the list.
STAPLE_SEEDS: list[str] = [
    "salt",
    "black pepper",
    "olive oil",
    "vegetable oil",
    "plain flour",
]

# "Same shopping item" groupings (2026-09-10 — see CLAUDE.md > Ingredient Aliases). Seeded
# with the one group that motivated the feature: "canola oil" and "oil spray" fold onto
# "vegetable oil" — which is already a STAPLE_SEED above, so this also means those recipe
# wordings now correctly match the existing vegetable-oil staple, not just each other.
# "olive oil" (also already a staple) is deliberately left OUT of this group — a household
# commonly wants it kept distinct from a neutral oil (dressing vs frying), and merging
# genuinely different products risks silently under-buying one of them. As with every other
# list on this page: add more groups via Settings only when a real gap shows up in use, not
# pre-emptively.
#
# 2026-09-10 (second kickoff, lemon/lime juice -> whole fruit): a group may also carry an
# optional quantity/unit equivalence pair (alias_qty/alias_unit ~= canonical_qty/
# canonical_unit) — "2 tbsp lemon juice" and "1 tsp lemon zest" both fold onto "lemon" as a
# bare count (canonical_unit=None, same as recipe_ingredients.unit=NULL for unitless
# produce). The ratios are rough kitchen approximations (a real lemon's yield varies) — the
# consolidated line always shows what it was converted FROM (services/session_consolidation.py
# appends a "(from ...)" note) precisely because it's an approximation, unlike the pure-rename
# oil group above which merges silently. "orange juice" is deliberately NOT seeded — the
# maintainer flagged it as genuinely recipe-dependent (sometimes a real ingredient in its own
# right, e.g. a marinade base bought as a carton, not always a fresh-squeeze stand-in), so
# auto-converting it would be wrong often enough to not guess at.
INGREDIENT_ALIAS_SEEDS: list[dict] = [
    {"alias_name": "canola oil", "canonical_name": "vegetable oil"},
    {"alias_name": "oil spray", "canonical_name": "vegetable oil"},
    {
        "alias_name": "lemon juice", "canonical_name": "lemon",
        "alias_qty": 3, "alias_unit": "tbsp", "canonical_qty": 1, "canonical_unit": None,
        "note": "roughly 3 tbsp juice per lemon",
    },
    {
        # Seeded in tsp, not tbsp, even though "roughly 1 tbsp per lemon" is the same ratio —
        # recipes overwhelmingly call for zest in teaspoons, and the transform only applies
        # when a recipe's own unit exactly matches alias_unit (2026-09-10 hand-testing caught
        # this: a tsp-based recipe against a tbsp-seeded ratio silently fell back to a
        # name-only rename, which then hit an unrelated real conflict with a juice
        # contribution and got flagged needs_review instead of converting cleanly).
        "alias_name": "lemon zest", "canonical_name": "lemon",
        "alias_qty": 3, "alias_unit": "tsp", "canonical_qty": 1, "canonical_unit": None,
        "note": "roughly 3 tsp (1 tbsp) zest per lemon",
    },
    {
        "alias_name": "lime juice", "canonical_name": "lime",
        "alias_qty": 2, "alias_unit": "tbsp", "canonical_qty": 1, "canonical_unit": None,
        "note": "roughly 2 tbsp juice per lime (limes are smaller than lemons)",
    },
    {
        "alias_name": "lime zest", "canonical_name": "lime",
        "alias_qty": 2, "alias_unit": "tsp", "canonical_qty": 1, "canonical_unit": None,
        "note": "roughly 2 tsp zest per lime",
    },
]

# Unit-spelling canonicalisation (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling >
# Layer A). A small, ONE-TIME, universal set of English cooking-measurement word-forms — not
# per-ingredient, so this isn't the admin the maintainer is avoiding.
#
# Only the BASE (already-singular) form of each word-form needs a row: resolve_unit() always
# runs strip_plural() before consulting this map, so a plural like "grams" or "teaspoons"
# already arrives here as "gram"/"teaspoon" — adding "grams" -> "g" as well would just be a
# dead, never-reached row. The two exceptions are units short enough (<=3 chars) that
# strip_plural()'s length guard deliberately leaves them alone (to avoid over-stripping — see
# that function's docstring), so "kgs"/"mls" need their own explicit rows.
UNIT_SYNONYM_SEEDS: list[dict] = [
    {"alias_unit": "gram", "canonical_unit": "g"},
    {"alias_unit": "kilogram", "canonical_unit": "kg"},
    {"alias_unit": "kgs", "canonical_unit": "kg"},
    {"alias_unit": "millilitre", "canonical_unit": "ml"},
    {"alias_unit": "milliliter", "canonical_unit": "ml"},
    {"alias_unit": "mls", "canonical_unit": "ml"},
    # Lowercase "l", not "L" -- services/unit_synonyms.py normalises canonical_unit lowercase
    # the same as alias_unit (consistent with every other normalised field in the app), and
    # it makes no functional difference here: consolidation.py's volume-display branch
    # hardcodes "L" for a >=1000ml total regardless of the input unit's casing.
    {"alias_unit": "litre", "canonical_unit": "l"},
    {"alias_unit": "liter", "canonical_unit": "l"},
    # No "l" -> "L" row: consolidation.py's _dimension()/_ML_PER already lowercase and match
    # "l" as volume regardless of input casing, and the display branch always hardcodes "L"
    # for a >=1000ml total — the casing genuinely doesn't matter anywhere downstream, so a
    # synonym row here would be dead weight (and, once case-folded, a self-alias anyway —
    # create_synonym() would reject "l" -> "L" for exactly that reason).
    {"alias_unit": "teaspoon", "canonical_unit": "tsp"},
    {"alias_unit": "tablespoon", "canonical_unit": "tbsp"},
    {"alias_unit": "tbs", "canonical_unit": "tbsp"},
]

# Coarse ingredients (2026-09-12 — see CLAUDE.md > Ingredient Unit Handling > Layer D).
# Skip quantity/unit math entirely at consolidation: any nonzero need resolves straight to a
# purchase-label count. Seeded with the maintainer's own motivating example (parsley) plus
# its obvious fresh-herb siblings — same "exercise it immediately" call as the oil-variant
# and lemon/lime alias seeds. recipes_per_pack is a rough, editable guess, not derived from
# anything — see the Known limitation note in CLAUDE.md > Ingredient Unit Handling.
COARSE_INGREDIENT_SEEDS: list[dict] = [
    {"name": "parsley", "purchase_label": "bunch", "recipes_per_pack": 3},
    {"name": "coriander", "purchase_label": "bunch", "recipes_per_pack": 3},
    {"name": "mint", "purchase_label": "bunch", "recipes_per_pack": 3},
    {"name": "basil", "purchase_label": "bunch", "recipes_per_pack": 3},
]


def seed_reference_data(db: Session) -> dict:
    """Insert any missing preseeded product units and staples. Idempotent.

    Returns a small dict summarising how many rows were added.
    """
    added_units = 0
    for row in PRODUCT_UNIT_SEEDS:
        # Idempotency keys off (ingredient_name, purchase_label) — the Phase 4 uniqueness —
        # so a second pack size for an already-seeded ingredient still gets inserted.
        exists = (
            db.query(ProductUnit)
            .filter(
                ProductUnit.ingredient_name == row["ingredient_name"],
                ProductUnit.purchase_label == row["purchase_label"],
            )
            .first()
        )
        if exists is None:
            db.add(ProductUnit(is_preseeded=True, **row))
            added_units += 1

    added_staples = 0
    for name in STAPLE_SEEDS:
        exists = db.query(Staple).filter(Staple.name == name).first()
        if exists is None:
            db.add(Staple(name=name))
            added_staples += 1

    added_aliases = 0
    for row in INGREDIENT_ALIAS_SEEDS:
        exists = (
            db.query(IngredientAlias)
            .filter(IngredientAlias.alias_name == row["alias_name"])
            .first()
        )
        if exists is None:
            db.add(IngredientAlias(**row))
            added_aliases += 1

    added_unit_synonyms = 0
    for row in UNIT_SYNONYM_SEEDS:
        exists = (
            db.query(UnitSynonym).filter(UnitSynonym.alias_unit == row["alias_unit"]).first()
        )
        if exists is None:
            db.add(UnitSynonym(**row))
            added_unit_synonyms += 1

    added_coarse = 0
    for row in COARSE_INGREDIENT_SEEDS:
        exists = (
            db.query(CoarseIngredient).filter(CoarseIngredient.name == row["name"]).first()
        )
        if exists is None:
            db.add(CoarseIngredient(**row))
            added_coarse += 1

    db.commit()
    result = {
        "product_units_added": added_units,
        "staples_added": added_staples,
        "ingredient_aliases_added": added_aliases,
        "unit_synonyms_added": added_unit_synonyms,
        "coarse_ingredients_added": added_coarse,
    }
    logger.info("Reference data seed: %s", result)
    return result

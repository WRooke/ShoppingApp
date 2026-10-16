"""Unit tests for app/services/checklist_display.py — display names (rewritten 2026-10-06,
Chunk 6.7 (user-feedback batch); see that module's docstring and docs/ingredient-handling.md > Display names).

Two kinds of test: the rule itself (the household's own wording), and — more important — the
property that makes the change safe: **a display string always normalises back to its key and the
title-cased AnyList name always matches its own checklist row**, so nothing about matching,
consolidation, aliases or re-pushing can be affected by what is displayed.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.services import checklist, text_normalize
from app.services import checklist_display as cd
from app.services import ingredient_aliases as ia
from app.services import recipes as recipes_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _recipe_with(db, name, ingredients):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=name, source_type="manual", base_servings=4,
            ingredients=[RecipeIngredientCreate(**i) for i in ingredients],
        ),
        allow_duplicate=True,
    )


def _wrote(db, *names, unit="g"):
    """One recipe whose ingredients are exactly `names` (written as given)."""
    _recipe_with(db, f"R{random.random()}", [{"name": n, "quantity": 1, "unit": unit} for n in names])


def key_of(name):
    return text_normalize.normalise_ingredient_name(name)


# --- the rule: the household's own wording -----------------------------------------------------


def test_plural_nouns_the_household_writes_in_the_plural_stay_plural_with_any_unit(db):
    _wrote(db, "black beans", "cashew nuts", "corn chips", "salted peanuts")
    for written in ("black beans", "cashew nuts", "corn chips", "salted peanuts"):
        for q, u in ((None, None), (800, "g"), (5, "cup"), (3, None), (12, "clove")):
            assert cd.display_name(db, key_of(written), q, u) == written


def test_mass_nouns_are_never_pluralised_whatever_the_amount_or_stray_rows(db):
    # real-data shapes that produced "salts"/"parmesans"/"vegetable oils" under the old rule
    _wrote(db, "salt", "parmesan", "vegetable oil", "olive oil", "flour", "black pepper")
    _wrote(db, "salt", "parmesan", unit=None)  # stray unitless rows made the old logic call them countable
    _wrote(db, "oil spray", unit=None)
    ia.create_alias(db, IngredientAliasCreate(alias_name="oil spray", canonical_name="vegetable oil"))
    for written in ("salt", "parmesan", "vegetable oil", "olive oil", "flour", "black pepper"):
        for q, u in ((None, None), (2, "tsp"), (35, "g"), (4, "tbsp"), (3, None), (2, "kg")):
            assert cd.display_name(db, key_of(written), q, u) == written, (written, q, u)


def test_a_count_of_one_or_less_is_the_singular_key(db):
    _wrote(db, "carrots", "eggs", unit=None)
    assert cd.display_name(db, "carrot", 1, None) == "carrot"
    assert cd.display_name(db, "egg", 0.5, None) == "egg"
    assert cd.display_name(db, "carrot", 3, None) == "carrots"  # the household wrote the plural


def test_a_bare_count_above_one_prefers_a_plural_form_if_one_was_written(db):
    _wrote(db, "carrot", "carrot", "carrots", unit=None)  # singular is the majority...
    assert cd.display_name(db, "carrot", 3, None) == "carrots"  # ...but a count of several wants the plural
    assert cd.display_name(db, "carrot", 500, "g") == "carrot"  # with a weight the usual form is used


def test_nothing_is_ever_invented_a_singular_only_household_stays_singular(db):
    # An earlier draft pluralised "a bare count by definition"; real data showed that makes
    # "black peppers"/"flours" out of stray unitless rows, so a plural is only ever one the
    # household wrote.
    _wrote(db, "chicken thigh", "black pepper", unit=None)
    assert cd.display_name(db, "chicken thigh", 8, None) == "chicken thigh"
    assert cd.display_name(db, "black pepper", 2, None) == "black pepper"


def test_ties_between_written_forms_pick_the_longer_then_alphabetical_deterministically(db):
    _wrote(db, "garlic clove", "garlic cloves")
    assert cd.display_name(db, "garlic clove", 500, "g") == "garlic cloves"


def test_hyphen_and_space_spellings_are_one_form(db):
    _wrote(db, "extra-virgin olive oil", "extra virgin olive oil", "extra-virgin olive oil")
    assert cd.display_name(db, key_of("extra virgin olive oil"), 2, "tbsp") == "extra virgin olive oil"


def test_names_containing_or_are_shown_exactly_as_written(db):
    _wrote(db, "pita bread or flatbreads")
    k = key_of("pita bread or flatbreads")
    assert k == "pita bread or flatbread"
    assert cd.display_name(db, k, 2, None) == "pita bread or flatbreads"
    assert cd.display_name(db, k, 200, "g") == "pita bread or flatbreads"


def test_a_confirmed_substitution_counts_as_the_wording_of_the_substitute(db):
    _recipe_with(db, "R", [{"name": "corn cobs", "quantity": 2, "unit": "can",
                            "resolved_ingredient": "canned corn kernels", "resolved_quantity": 2, "resolved_unit": "can"}])
    assert cd.display_name(db, key_of("canned corn kernels"), 2, "can") == "canned corn kernels"
    assert cd.display_name(db, key_of("corn cobs"), 2, "can") == "corn cob"  # not counted for the original name


# --- ingredients the household never wrote under their own key ---------------------------------


def test_alias_canonical_with_no_rows_of_its_own_uses_its_members_mostly_plural_wording(db):
    _wrote(db, "diced tomatoes", "crushed tomatoes", "tomato passata")
    ia.create_alias(db, IngredientAliasCreate(alias_name="diced tomato", canonical_name="canned tomato"))
    ia.create_alias(db, IngredientAliasCreate(alias_name="crushed tomato", canonical_name="canned tomato"))
    assert cd.display_name(db, "canned tomato", 800, "g") == "canned tomatoes"


def test_alias_canonical_whose_members_are_singular_stays_singular(db):
    _wrote(db, "oil spray", "canola oil")
    ia.create_alias(db, IngredientAliasCreate(alias_name="oil spray", canonical_name="cooking oil"))
    ia.create_alias(db, IngredientAliasCreate(alias_name="canola oil", canonical_name="cooking oil"))
    assert cd.display_name(db, "cooking oil", 4, "tbsp") == "cooking oil"  # not "cooking oils"


def test_a_canonical_WITH_its_own_rows_ignores_its_members_wording(db):
    # the exact "vegetable oils" bug: a stray member row must not move the canonical's own wording
    _wrote(db, "vegetable oil", "oil spray", "canola oils")
    ia.create_alias(db, IngredientAliasCreate(alias_name="oil spray", canonical_name="vegetable oil"))
    ia.create_alias(db, IngredientAliasCreate(alias_name="canola oil", canonical_name="vegetable oil"))
    assert cd.display_name(db, "vegetable oil", 4, "tbsp") == "vegetable oil"


def test_unknown_ingredient_and_no_database_fall_back_to_the_key(db):
    assert cd.display_name(db, "brand new ingredient", 3, None) == "brand new ingredient"
    assert cd.display_name(None, "salt", None, None) == "salt"
    assert cd.display_name(None, "salt", 2, "tsp") == "salt"


def test_computed_plurals_are_never_made_for_names_where_only_the_last_word_would_change(db):
    _wrote(db, "cheddar cheeses or monterey jacks")  # members of a canonical -> computed plural candidate
    ia.create_alias(db, IngredientAliasCreate(alias_name="cheddar cheese or monterey jack", canonical_name="melting cheese or jack"))
    assert cd.display_name(db, "melting cheese or jack", 200, "g") == "melting cheese or jack"


# --- the safety property ----------------------------------------------------------------------


AMOUNTS = [(None, None), (1, None), (0.5, None), (3, None), (500, "g"), (2, "tbsp"), (12, "clove"), (2, "can")]


def _check_property(db, keys):
    index = cd.WordingIndex.build(db)
    for key in keys:
        for q, u in AMOUNTS:
            shown = cd.display_name(db, key, q, u, index)
            assert text_normalize.normalise_ingredient_name(shown) == key, (key, q, u, shown)
            pushed = text_normalize.title_case_name(shown)
            # the name pushed to AnyList must match its own checklist row on the next push
            assert checklist._names_match(key, pushed), (key, q, u, pushed)
            # ...and so must the old spelling a previous push may have left on the list
            assert checklist._names_match(key, key.title()), key


REAL_SHAPES = [
    "black beans", "black bean", "salt", "salts", "parmesan", "olive oil", "vegetable oils", "cashew nuts",
    "unsalted cashew nut", "broccoli florets", "corn chips", "canned tomatoes", "rice vermicelli noodles",
    "salted peanuts", "panko breadcrumbs", "pita bread or flatbreads", "cheddar cheese or monterey jack",
    "chicken thighs", "eggs", "egg", "carrots", "garlic cloves", "spring onions", "tomatoes (canned)",
    "extra-virgin olive oil", "2% milk", "baker's chocolate", "molasses", "hummus", "couscous",
    "asparagus", "cheeses", "cheese", "swiss chard", "chillies", "chilli flakes", "mangoes", "jalapenos",
    "half-and-half", "tofu", "chorizo", "lemongrass", "watercress", "bass fillets", "brownies", "fries",
]


def test_property_holds_for_every_awkward_shape_the_audit_found(db):
    _wrote(db, *REAL_SHAPES)
    _check_property(db, sorted({key_of(n) for n in REAL_SHAPES}))


def test_property_holds_with_aliases_and_members_mixed_in(db):
    _wrote(db, *REAL_SHAPES)
    for member, canonical in (("diced tomatoes", "canned tomatoes"), ("salts", "sea salt"),
                              ("cheeses", "cheese"), ("molasses", "treacle"), ("hummus", "dips")):
        try:
            ia.create_alias(db, IngredientAliasCreate(alias_name=member, canonical_name=canonical))
        except Exception:  # noqa: BLE001 — duplicate etc. is fine here
            pass
    keys = {key_of(n) for n in REAL_SHAPES} | {key_of(c) for c in ("canned tomatoes", "sea salt", "treacle", "dips")}
    _check_property(db, sorted(keys))


def test_property_holds_for_randomly_generated_wordings(db):
    rng = random.Random(6702)
    heads = ["black", "red", "dried", "fresh", "baby", "smoked", "unsalted", "ground", "sweet", "frozen"]
    tails = ["bean", "capsicum", "oil", "salt", "chip", "nut", "flake", "leaf", "berry", "potato", "tomato",
             "cheese", "molasses", "glass", "bass", "hummus", "mango", "box", "fry", "peach", "dish", "wolf"]
    names = set()
    for _ in range(300):
        base = f"{rng.choice(heads)} {rng.choice(tails)}"
        names.add(rng.choice([base, base + "s", base + "es", base.replace(" ", "-")]))
    _wrote(db, *sorted(names))
    _check_property(db, sorted({key_of(n) for n in names}))


def test_display_is_stable_across_calls_with_and_without_a_shared_index(db):
    _wrote(db, "black beans", "carrots", "carrot")
    index = cd.WordingIndex.build(db)
    for key in ("black bean", "carrot", "never seen"):
        for q, u in AMOUNTS:
            assert cd.display_name(db, key, q, u) == cd.display_name(db, key, q, u, index)


# --- display_unit (unchanged by the 2026-10-06 rewrite) -----------------------------------------


def test_display_unit_pluralises_a_discrete_counting_unit_when_not_one():
    assert cd.display_unit("clove", 12) == "cloves"
    assert cd.display_unit("sprig", 4) == "sprigs"


def test_display_unit_stays_singular_at_quantity_one():
    assert cd.display_unit("clove", 1) == "clove"


def test_display_unit_never_pluralises_a_measured_unit():
    assert cd.display_unit("g", 500) == "g"
    assert cd.display_unit("ml", 250) == "ml"
    assert cd.display_unit("tbsp", 3) == "tbsp"


def test_display_unit_passes_through_none():
    assert cd.display_unit(None, 5) is None

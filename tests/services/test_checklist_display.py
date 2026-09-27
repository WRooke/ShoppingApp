"""Unit tests for app/services/checklist_display.py — natural-English display names for the
checklist (2026-09-27). See that module's docstring for the full "why not just use a library"
reasoning behind the data-driven countability check.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
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
    )


# --- is_known_countable --------------------------------------------------------------------


def test_never_seen_as_bare_count_is_not_countable(db):
    _recipe_with(db, "R", [{"name": "flour", "quantity": 500, "unit": "g"}])
    assert cd.is_known_countable(db, "flour") is False


def test_seen_as_bare_count_is_countable(db):
    _recipe_with(db, "R", [{"name": "egg", "quantity": 2, "unit": None}])
    assert cd.is_known_countable(db, "egg") is True


def test_countable_history_pools_across_alias_group(db):
    _recipe_with(db, "R", [{"name": "canola oil", "quantity": 1, "unit": None}])
    ia.create_alias(db, IngredientAliasCreate(alias_name="canola oil", canonical_name="vegetable oil"))
    # "vegetable oil" itself was never recorded as a bare count, but its alias group member was.
    assert cd.is_known_countable(db, "vegetable oil") is True


def test_unknown_ingredient_defaults_to_not_countable(db):
    assert cd.is_known_countable(db, "an ingredient never seen before") is False


# --- display_name ----------------------------------------------------------------------------


def test_display_name_singular_count_of_one_stays_singular(db):
    _recipe_with(db, "R", [{"name": "egg", "quantity": 1, "unit": None}])
    assert cd.display_name(db, "egg", 1, None) == "egg"


def test_display_name_pluralises_a_count_noun_when_count_is_not_one(db):
    _recipe_with(db, "R", [{"name": "chicken thigh", "quantity": 1, "unit": None}])
    assert cd.display_name(db, "chicken thigh", 8, None) == "chicken thighs"
    assert cd.display_name(db, "chicken thigh", 0, None) == "chicken thighs"


def test_display_name_pluralises_a_count_noun_with_a_weight_unit(db):
    # The user's own stated rule: "500g chicken thighs" — plural even though it's a weight, not
    # a discrete count, as long as this household's data confirms it's a genuine count noun.
    _recipe_with(db, "R", [{"name": "chicken thigh", "quantity": 1, "unit": None}])
    assert cd.display_name(db, "chicken thigh", 500, "g") == "chicken thighs"


def test_display_name_never_pluralises_a_mass_noun_regardless_of_amount(db):
    _recipe_with(db, "R", [{"name": "flour", "quantity": 500, "unit": "g"}])
    assert cd.display_name(db, "flour", 500, "g") == "flour"
    assert cd.display_name(db, "flour", 2, "kg") == "flour"


def test_display_name_never_seen_as_countable_defaults_to_unchanged(db):
    # Safe-failure direction: an ingredient never yet recorded as a bare count stays singular,
    # a cosmetic miss rather than a guess.
    assert cd.display_name(db, "brand new ingredient", 3, None) == "brand new ingredient"


def test_display_name_none_quantity_never_pluralises():
    # needs_review-not-yet-resolved / genuine "to taste" lines — no concrete amount to reason
    # a plural from.
    assert cd.display_name(None, "salt", None, None) == "salt"


def test_display_name_never_pluralises_when_a_discrete_counting_unit_is_present(db):
    # Live-test finding (2026-09-27): after the extraction prompt was fixed to give garlic a
    # real "clove" unit instead of a bare count, the checklist still showed "garlics" next to
    # "12 clove" — wrong at any quantity. The UNIT is what naturally pluralises here ("12
    # cloves of garlic"), never the ingredient name. See display_unit for the unit's own half.
    _recipe_with(db, "R", [{"name": "garlic", "quantity": 1, "unit": None}])
    assert cd.display_name(db, "garlic", 12, "clove") == "garlic"
    assert cd.display_name(db, "garlic", 1, "clove") == "garlic"


def test_display_name_still_pluralises_with_a_measured_unit(db):
    # Contrast case: a *measured* unit (g/ml/tsp/...) is not a discrete counting unit, so the
    # pre-existing "500g chicken thighs" behaviour must be unaffected by the fix above.
    _recipe_with(db, "R", [{"name": "chicken thigh", "quantity": 1, "unit": None}])
    assert cd.display_name(db, "chicken thigh", 500, "g") == "chicken thighs"


# --- display_unit ----------------------------------------------------------------------------


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

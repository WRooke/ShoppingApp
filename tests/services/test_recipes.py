"""Unit tests for app/services/recipes.py — exercised directly against a DB
session, no FastAPI/HTTP involved (see CLAUDE.md > Code Architecture &
Maintainability). Router-level behaviour is covered separately by
tests/routers/test_recipes.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.recipes import (
    RecipeCreate,
    RecipeIngredientCreate,
    RecipeIngredientUpdate,
    RecipeUpdate,
)
from app.services import recipes as recipes_service


@pytest.fixture()
def db():
    # In-memory SQLite, fresh schema per test — genuinely no shared state, no network.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


def _make_recipe(**overrides) -> RecipeCreate:
    payload = {
        "name": "Spaghetti Bolognese",
        "source_type": "manual",
        "base_servings": 4,
        "ingredients": [
            RecipeIngredientCreate(name="  Beef Mince  ", quantity=500, unit="g"),
            RecipeIngredientCreate(name="onion", quantity=1, unit=None),
        ],
    }
    payload.update(overrides)
    return RecipeCreate(**payload)


def test_create_recipe_normalises_ingredient_names(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    assert recipe.id is not None
    assert [i.name for i in recipe.ingredients] == ["beef mince", "onion"]


def test_get_recipe_raises_when_missing(db):
    with pytest.raises(recipes_service.RecipeNotFoundError):
        recipes_service.get_recipe(db, 999)


def test_list_recipes_excludes_archived_by_default(db):
    r1 = recipes_service.create_recipe(db, _make_recipe(name="Tacos"))
    recipes_service.create_recipe(db, _make_recipe(name="Curry"))
    recipes_service.archive_recipe(db, r1.id)

    results, total = recipes_service.list_recipes(db)

    assert total == 1
    assert [r.name for r in results] == ["Curry"]


def test_list_recipes_include_archived_true_shows_everything(db):
    r1 = recipes_service.create_recipe(db, _make_recipe(name="Tacos"))
    recipes_service.create_recipe(db, _make_recipe(name="Curry"))
    recipes_service.archive_recipe(db, r1.id)

    results, total = recipes_service.list_recipes(db, include_archived=True)

    assert total == 2
    assert {r.name for r in results} == {"Tacos", "Curry"}


def test_list_recipes_search_is_case_insensitive_substring(db):
    recipes_service.create_recipe(db, _make_recipe(name="Chicken Curry"))
    recipes_service.create_recipe(db, _make_recipe(name="Beef Tacos"))

    results, total = recipes_service.list_recipes(db, search="CURRY")

    assert total == 1
    assert results[0].name == "Chicken Curry"


def test_list_recipes_pagination(db):
    for i in range(5):
        recipes_service.create_recipe(db, _make_recipe(name=f"Recipe {i}"))

    page1, total = recipes_service.list_recipes(db, limit=2, offset=0)
    page2, _ = recipes_service.list_recipes(db, limit=2, offset=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


def test_update_recipe_partial_update_only_touches_sent_fields(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    updated = recipes_service.update_recipe(
        db, recipe.id, RecipeUpdate(rating="up", notes="great with garlic bread")
    )

    assert updated.rating == "up"
    assert updated.notes == "great with garlic bread"
    assert updated.name == "Spaghetti Bolognese"  # untouched


def test_update_recipe_raises_when_missing(db):
    with pytest.raises(recipes_service.RecipeNotFoundError):
        recipes_service.update_recipe(db, 999, RecipeUpdate(rating="up"))


def test_archive_recipe_sets_archived_at(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())
    assert recipe.archived_at is None

    recipes_service.archive_recipe(db, recipe.id)

    reloaded = recipes_service.get_recipe(db, recipe.id)
    assert reloaded.archived_at is not None


def test_add_ingredient_normalises_name(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    ingredient = recipes_service.add_ingredient(
        db, recipe.id, RecipeIngredientCreate(name=" Spring Onion ", quantity=2)
    )

    assert ingredient.name == "spring onion"
    assert ingredient.recipe_id == recipe.id


def test_add_ingredient_raises_when_recipe_missing(db):
    with pytest.raises(recipes_service.RecipeNotFoundError):
        recipes_service.add_ingredient(db, 999, RecipeIngredientCreate(name="salt", quantity=1))


def test_update_ingredient_partial_update(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())
    ingredient_id = recipe.ingredients[0].id

    updated = recipes_service.update_ingredient(
        db, recipe.id, ingredient_id, RecipeIngredientUpdate(quantity=750)
    )

    assert updated.quantity == 750
    assert updated.unit == "g"  # untouched


def test_update_ingredient_raises_when_ingredient_belongs_to_different_recipe(db):
    recipe1 = recipes_service.create_recipe(db, _make_recipe(name="Recipe 1"))
    recipe2 = recipes_service.create_recipe(db, _make_recipe(name="Recipe 2"))
    other_ingredient_id = recipe2.ingredients[0].id

    with pytest.raises(recipes_service.IngredientNotFoundError):
        recipes_service.update_ingredient(
            db, recipe1.id, other_ingredient_id, RecipeIngredientUpdate(quantity=1)
        )


def test_delete_ingredient_removes_row(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())
    ingredient_id = recipe.ingredients[0].id

    recipes_service.delete_ingredient(db, recipe.id, ingredient_id)

    reloaded = recipes_service.get_recipe(db, recipe.id)
    assert [i.id for i in reloaded.ingredients] == [
        i.id for i in recipe.ingredients if i.id != ingredient_id
    ]


def test_delete_ingredient_raises_when_missing(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    with pytest.raises(recipes_service.IngredientNotFoundError):
        recipes_service.delete_ingredient(db, recipe.id, 999)

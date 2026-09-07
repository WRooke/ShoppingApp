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
from app.models.store import ProductSection
from app.schemas.capture import CaptureConfirmRequest, CaptureIngredientConfirm
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
        # distinct, non-fuzzy-similar names; allow_duplicate as a belt-and-braces
        recipes_service.create_recipe(
            db, _make_recipe(name=f"Recipe {i}"), allow_duplicate=True
        )

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


def test_create_recipe_stores_m8_resolved_transform(db):
    recipe = recipes_service.create_recipe(
        db,
        _make_recipe(
            ingredients=[
                RecipeIngredientCreate(
                    name="corn cobs", quantity=2, unit="cob",
                    resolved_ingredient="Canned Corn",
                    resolved_quantity=2, resolved_unit=" Can ",
                )
            ]
        ),
    )
    ing = recipe.ingredients[0]
    assert ing.resolved_ingredient == "canned corn"
    assert (ing.resolved_quantity, ing.resolved_unit) == (2, "can")


def test_create_recipe_drops_transform_without_a_name_swap(db):
    # schema rejects qty/unit with no resolved_ingredient
    with pytest.raises(ValueError):
        _make_recipe(
            ingredients=[
                RecipeIngredientCreate(
                    name="corn", quantity=2, unit="cob",
                    resolved_quantity=2, resolved_unit="can",
                )
            ]
        )


def test_update_ingredient_clearing_swap_also_clears_the_transform(db):
    recipe = recipes_service.create_recipe(
        db,
        _make_recipe(
            ingredients=[
                RecipeIngredientCreate(
                    name="corn cobs", quantity=2, unit="cob",
                    resolved_ingredient="canned corn",
                    resolved_quantity=2, resolved_unit="can",
                )
            ]
        ),
    )
    ing_id = recipe.ingredients[0].id

    reverted = recipes_service.update_ingredient(
        db, recipe.id, ing_id, RecipeIngredientUpdate(resolved_ingredient=None)
    )
    assert reverted.resolved_ingredient is None
    assert reverted.resolved_quantity is None and reverted.resolved_unit is None


def test_update_ingredient_raises_when_ingredient_belongs_to_different_recipe(db):
    recipe1 = recipes_service.create_recipe(db, _make_recipe(name="Alpha Dish"))
    recipe2 = recipes_service.create_recipe(db, _make_recipe(name="Bravo Dish"))
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


# --- create_recipe_from_capture (Phase 3, Chunk 3.4) ------------------------


def _make_capture_confirm(**overrides) -> CaptureConfirmRequest:
    payload = {
        "name": "Weeknight Beef Tacos",
        "source_type": "url",
        "source_url": "https://example.com/tacos",
        "base_servings": 4,
        "cuisine": "mexican",
        "protein": "beef mince",
        "ingredients": [
            CaptureIngredientConfirm(
                name="  Beef Mince  ", quantity=500, unit="g", suggested_section="meat & seafood"
            ),
            CaptureIngredientConfirm(name="onion", quantity=1, unit=None, suggested_section="produce"),
        ],
    }
    payload.update(overrides)
    return CaptureConfirmRequest(**payload)


def test_create_recipe_from_capture_saves_recipe_and_ingredients(db):
    recipe = recipes_service.create_recipe_from_capture(db, _make_capture_confirm())

    assert recipe.id is not None
    assert recipe.source_type == "url"
    assert recipe.source_url == "https://example.com/tacos"
    assert recipe.cuisine == "mexican"
    assert [i.name for i in recipe.ingredients] == ["beef mince", "onion"]


def test_create_recipe_from_capture_writes_product_sections(db):
    recipes_service.create_recipe_from_capture(db, _make_capture_confirm())

    sections = {row.ingredient_name: (row.section_name, row.source) for row in db.query(ProductSection).all()}
    assert sections["beef mince"] == ("meat & seafood", "ai_suggested")
    assert sections["onion"] == ("produce", "ai_suggested")


def test_create_recipe_from_capture_skips_ingredient_with_no_suggested_section(db):
    data = _make_capture_confirm(
        ingredients=[CaptureIngredientConfirm(name="salt", quantity=1, unit=None, suggested_section=None)]
    )
    recipes_service.create_recipe_from_capture(db, data)

    assert db.query(ProductSection).count() == 0


def test_create_recipe_from_capture_never_overwrites_existing_product_section(db):
    db.add(ProductSection(ingredient_name="beef mince", section_name="pantry", source="user_corrected"))
    db.commit()

    recipes_service.create_recipe_from_capture(db, _make_capture_confirm())

    row = db.query(ProductSection).filter_by(ingredient_name="beef mince").one()
    assert row.section_name == "pantry"
    assert row.source == "user_corrected"


# --- source provenance (Chunk 3.7) ----------------------------------------


def test_create_recipe_stores_source_provenance(db):
    recipe = recipes_service.create_recipe(
        db, _make_recipe(source_book="Ottolenghi SIMPLE", source_page="142-143")
    )

    assert recipe.source_book == "Ottolenghi SIMPLE"
    assert recipe.source_page == "142-143"


def test_create_recipe_trims_provenance_and_nulls_blanks(db):
    recipe = recipes_service.create_recipe(
        db, _make_recipe(source_book="  Ottolenghi SIMPLE  ", source_page="   ")
    )

    assert recipe.source_book == "Ottolenghi SIMPLE"  # trimmed
    assert recipe.source_page is None  # whitespace-only -> not set


def test_create_recipe_defaults_provenance_to_none(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    assert recipe.source_book is None
    assert recipe.source_page is None


def test_create_recipe_from_capture_stores_source_provenance(db):
    recipe = recipes_service.create_recipe_from_capture(
        db, _make_capture_confirm(source_book="  Bittman: How to Cook Everything  ", source_page="88")
    )

    assert recipe.source_book == "Bittman: How to Cook Everything"
    assert recipe.source_page == "88"


def test_update_recipe_sets_source_provenance(db):
    recipe = recipes_service.create_recipe(db, _make_recipe())

    updated = recipes_service.update_recipe(
        db, recipe.id, RecipeUpdate(source_book="Ottolenghi SIMPLE", source_page="142")
    )

    assert updated.source_book == "Ottolenghi SIMPLE"
    assert updated.source_page == "142"
    assert updated.name == "Spaghetti Bolognese"  # untouched


# --- duplicate recipe prevention (Phase 4 — CLAUDE.md > Duplicate Recipe Prevention) -----


def test_find_possible_duplicates_exact_name_case_and_whitespace_insensitive(db):
    recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    matches = recipes_service.find_possible_duplicates(db, name="  spaghetti   bolognese ")

    assert [m.matched_signal for m in matches] == ["name_exact"]
    assert matches[0].archived is False


def test_find_possible_duplicates_source_url_normalised(db):
    recipes_service.create_recipe(
        db, _make_recipe(name="A", source_url="https://Example.com/recipe/")
    )

    matches = recipes_service.find_possible_duplicates(
        db, name="totally different", source_url="https://example.com/recipe?utm_source=news#top"
    )

    assert [m.matched_signal for m in matches] == ["source_url"]


def test_find_possible_duplicates_book_and_overlapping_page_range(db):
    recipes_service.create_recipe(
        db, _make_recipe(name="X", source_book="Ottolenghi SIMPLE", source_page="142-143")
    )

    matches = recipes_service.find_possible_duplicates(
        db, name="unrelated", source_book="ottolenghi simple", source_page="143 & 150"
    )

    assert [m.matched_signal for m in matches] == ["book_page"]


def test_find_possible_duplicates_book_without_page_overlap_does_not_match(db):
    recipes_service.create_recipe(
        db, _make_recipe(name="X", source_book="Ottolenghi SIMPLE", source_page="10")
    )

    matches = recipes_service.find_possible_duplicates(
        db, name="unrelated", source_book="Ottolenghi SIMPLE", source_page="99"
    )

    assert matches == []


def test_find_possible_duplicates_fuzzy_name(db):
    recipes_service.create_recipe(db, _make_recipe(name="Weeknight Beef Tacos"))

    matches = recipes_service.find_possible_duplicates(db, name="Beef Tacos, Weeknight")

    assert [m.matched_signal for m in matches] == ["fuzzy_name"]


def test_find_possible_duplicates_unrelated_name_no_match(db):
    recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    assert recipes_service.find_possible_duplicates(db, name="Thai Green Curry") == []


def test_find_possible_duplicates_excludes_self(db):
    r = recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    matches = recipes_service.find_possible_duplicates(
        db, name="Spaghetti Bolognese", exclude_id=r.id
    )

    assert matches == []


def test_find_possible_duplicates_includes_archived_and_flags_it(db):
    r = recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))
    recipes_service.archive_recipe(db, r.id)

    matches = recipes_service.find_possible_duplicates(db, name="Spaghetti Bolognese")

    assert len(matches) == 1
    assert matches[0].archived is True


def test_find_possible_duplicates_ranks_strongest_signal_first(db):
    recipes_service.create_recipe(
        db, _make_recipe(name="URL match only", source_url="https://example.com/r")
    )
    recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    matches = recipes_service.find_possible_duplicates(
        db, name="Spaghetti Bolognese", source_url="https://example.com/r"
    )

    assert [m.matched_signal for m in matches] == ["source_url", "name_exact"]


def test_create_recipe_raises_on_possible_duplicate(db):
    recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    with pytest.raises(recipes_service.PossibleDuplicateRecipeError) as exc:
        recipes_service.create_recipe(db, _make_recipe(name="spaghetti bolognese"))

    assert exc.value.matches[0].matched_signal == "name_exact"


def test_create_recipe_allow_duplicate_bypasses_the_check(db):
    recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))

    second = recipes_service.create_recipe(
        db, _make_recipe(name="Spaghetti Bolognese"), allow_duplicate=True
    )

    assert second.id is not None


def test_create_recipe_from_capture_raises_on_possible_duplicate(db):
    recipes_service.create_recipe_from_capture(db, _make_capture_confirm(name="Weeknight Beef Tacos"))

    with pytest.raises(recipes_service.PossibleDuplicateRecipeError):
        recipes_service.create_recipe_from_capture(
            db, _make_capture_confirm(name="Weeknight Beef Tacos", source_url=None)
        )


def test_unarchive_recipe_clears_archived_at(db):
    r = recipes_service.create_recipe(db, _make_recipe(name="Spaghetti Bolognese"))
    recipes_service.archive_recipe(db, r.id)

    restored = recipes_service.unarchive_recipe(db, r.id)

    assert restored.archived_at is None


def test_find_recipe_by_source_url_prefers_live_over_archived(db):
    archived = recipes_service.create_recipe(
        db, _make_recipe(name="Old", source_url="https://example.com/r"), allow_duplicate=True
    )
    recipes_service.archive_recipe(db, archived.id)
    live = recipes_service.create_recipe(
        db, _make_recipe(name="New", source_url="https://example.com/r/"), allow_duplicate=True
    )

    found = recipes_service.find_recipe_by_source_url(db, "https://example.com/r?utm_x=1")

    assert found.id == live.id

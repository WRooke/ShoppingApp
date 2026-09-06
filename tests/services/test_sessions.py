"""Unit tests for app/services/sessions.py — direct DB session, no HTTP.
Router behaviour is covered by tests/routers/test_sessions.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import (
    LeftoversSlotCreate,
    PlanningSessionCreate,
    PlanningSessionUpdate,
    SessionOverride,
    SessionRecipeCreate,
    SessionSlotUpdate,
)
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service
from app.services.scaling import DEFAULT_TARGET_SERVINGS


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


def _recipe(db, name="Test Dish", base_servings=4):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=name,
            source_type="manual",
            base_servings=base_servings,
            ingredients=[RecipeIngredientCreate(name="thing", quantity=1, unit="g")],
        ),
        allow_duplicate=True,
    )


# --- session CRUD ---------------------------------------------------------


def test_create_session_defaults_active_and_trims_label(db):
    s = sessions_service.create_session(db, PlanningSessionCreate(label="  Week of 14 Jul  "))
    assert s.id is not None
    assert s.status == "active"
    assert s.label == "Week of 14 Jul"


def test_get_session_raises_when_missing(db):
    with pytest.raises(sessions_service.SessionNotFoundError):
        sessions_service.get_session(db, 999)


def test_list_sessions_newest_first_and_status_filter(db):
    a = sessions_service.create_session(db, PlanningSessionCreate(label="A"))
    b = sessions_service.create_session(db, PlanningSessionCreate(label="B"))
    sessions_service.archive_session(db, a.id)

    all_rows, total = sessions_service.list_sessions(db)
    assert total == 2
    assert [s.id for s in all_rows] == [b.id, a.id]  # newest first

    archived, total_archived = sessions_service.list_sessions(db, status="archived")
    assert [s.id for s in archived] == [a.id] and total_archived == 1


def test_list_sessions_pagination(db):
    for i in range(5):
        sessions_service.create_session(db, PlanningSessionCreate(label=f"S{i}"))
    page1, total = sessions_service.list_sessions(db, limit=2, offset=0)
    page2, _ = sessions_service.list_sessions(db, limit=2, offset=2)
    assert total == 5 and len(page1) == 2 and len(page2) == 2
    assert {s.id for s in page1}.isdisjoint({s.id for s in page2})


def test_update_session_label_and_status(db):
    s = sessions_service.create_session(db, PlanningSessionCreate(label="X"))
    updated = sessions_service.update_session(
        db, s.id, PlanningSessionUpdate(label="Y", status="pushed")
    )
    assert updated.label == "Y" and updated.status == "pushed"


def test_archive_session_sets_status(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    assert sessions_service.archive_session(db, s.id).status == "archived"


# --- recipe slots -------------------------------------------------------


def test_add_session_recipe_defaults_servings_and_appends_sort_order(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2 = _recipe(db, "One"), _recipe(db, "Two")

    slot1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    slot2 = sessions_service.add_session_recipe(
        db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=6, day_of_week=3)
    )

    assert slot1.slot_type == "recipe"
    assert slot1.scaled_servings == DEFAULT_TARGET_SERVINGS  # default applied
    assert slot1.sort_order == 0 and slot2.sort_order == 1
    assert slot2.scaled_servings == 6 and slot2.day_of_week == 3


def test_add_session_recipe_unknown_recipe_raises(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    with pytest.raises(recipes_service.RecipeNotFoundError):
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=12345))


def test_add_session_recipe_unknown_session_raises(db):
    r = _recipe(db)
    with pytest.raises(sessions_service.SessionNotFoundError):
        sessions_service.add_session_recipe(db, 999, SessionRecipeCreate(recipe_id=r.id))


# --- leftovers slots --------------------------------------------------


def test_add_leftovers_slot_has_no_recipe_and_zero_servings(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    slot = sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate(day_of_week=5))
    assert slot.slot_type == "leftovers"
    assert slot.recipe_id is None
    assert slot.scaled_servings == 0
    assert slot.day_of_week == 5


def test_update_slot_scaled_servings_inert_on_leftovers(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    slot = sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate())
    updated = sessions_service.update_slot(
        db, s.id, slot.id, SessionSlotUpdate(scaled_servings=8, day_of_week=2)
    )
    assert updated.scaled_servings == 0  # ignored
    assert updated.day_of_week == 2  # applied


def test_update_slot_on_recipe_changes_servings(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id))
    updated = sessions_service.update_slot(
        db, s.id, slot.id, SessionSlotUpdate(scaled_servings=2)
    )
    assert updated.scaled_servings == 2


def test_remove_slot(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id))
    sessions_service.remove_slot(db, s.id, slot.id)
    assert sessions_service.get_session(db, s.id).recipes == []


def test_get_slot_wrong_session_raises(db):
    s1 = sessions_service.create_session(db, PlanningSessionCreate())
    s2 = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe(db)
    slot = sessions_service.add_session_recipe(db, s1.id, SessionRecipeCreate(recipe_id=r.id))
    with pytest.raises(sessions_service.SessionSlotNotFoundError):
        sessions_service.update_slot(db, s2.id, slot.id, SessionSlotUpdate(scaled_servings=2))


# --- reorder ---------------------------------------------------------


def test_reorder_slots_sets_sort_order_by_position(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2, r3 = _recipe(db, "A"), _recipe(db, "B"), _recipe(db, "C")
    s1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    s2 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id))
    s3 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r3.id))

    result = sessions_service.reorder_slots(db, s.id, [s3.id, s1.id, s2.id])

    assert [x.id for x in result] == [s3.id, s1.id, s2.id]
    assert [x.sort_order for x in result] == [0, 1, 2]


def test_reorder_slots_rejects_partial_or_foreign_id_list(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1, r2 = _recipe(db, "A"), _recipe(db, "B")
    s1 = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id))

    with pytest.raises(sessions_service.SlotOrderMismatchError):
        sessions_service.reorder_slots(db, s.id, [s1.id])  # missing one


# --- consolidate_session (Chunk 4.6) ---------------------------------


def _recipe_with(db, name, ings, base_servings=4):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=name,
            source_type="manual",
            base_servings=base_servings,
            ingredients=[RecipeIngredientCreate(**i) for i in ings],
        ),
        allow_duplicate=True,
    )


def test_consolidate_scales_and_sums_across_recipes(db):
    from app.models.catalog import ProductUnit

    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "Bol", [{"name": "beef mince", "quantity": 500, "unit": "g"}], base_servings=4)
    r2 = _recipe_with(db, "Chilli", [{"name": "beef mince", "quantity": 250, "unit": "g"}], base_servings=4)
    # r1 target 4 (x1) -> 500g; r2 target 6 (x1.5) -> 375g; total 875 -> ceil 25 -> 875
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=6))

    db.add(ProductUnit(ingredient_name="beef mince", purchase_label="500g pack", purchase_qty=500, purchase_unit="g"))
    db.commit()

    items = sessions_service.consolidate_session(db, s.id)
    assert len(items) == 1
    it = items[0]
    assert it.ingredient_name == "beef mince"
    assert it.total_quantity == 875 and it.total_unit == "g"
    assert it.display_qty == "2 × 500g pack"  # ceil(875/500)=2
    assert it.purchase_qty == 1000


def test_consolidate_leftovers_slot_contributes_nothing(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Soup", [{"name": "carrot", "quantity": 3, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.add_leftovers_slot(db, s.id, LeftoversSlotCreate(day_of_week=3))

    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["carrot"]
    assert items[0].total_quantity == 3


def test_consolidate_flags_is_staple(db):
    from app.services import settings as settings_service
    from app.schemas.settings import StapleCreate

    settings_service.create_staple(db, StapleCreate(name="olive oil"))
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Dressing", [{"name": "olive oil", "quantity": 30, "unit": "ml"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].is_staple is True


def test_consolidate_is_a_merge_preserving_have_it_and_add_to_list(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r1 = _recipe_with(db, "A", [{"name": "onion", "quantity": 2, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r1.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)

    # user marks the onion line
    onion = next(ci for ci in sessions_service.get_session(db, s.id).checklist_items if ci.ingredient_name == "onion")
    onion.have_it = "yes"
    onion.add_to_list = True
    db.commit()

    # add a second recipe and re-consolidate
    r2 = _recipe_with(db, "B", [{"name": "onion", "quantity": 1, "unit": None}, {"name": "garlic", "quantity": 2, "unit": None}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r2.id, scaled_servings=4))
    items = sessions_service.consolidate_session(db, s.id)

    by_name = {i.ingredient_name: i for i in items}
    assert by_name["onion"].total_quantity == 3  # recomputed
    assert by_name["onion"].have_it == "yes"  # preserved
    assert by_name["onion"].add_to_list is True  # preserved
    assert by_name["garlic"].have_it == "unknown"  # new line, default


def test_consolidate_removes_lines_no_longer_needed(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "A", [{"name": "onion", "quantity": 2, "unit": None}])
    slot = sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)
    assert len(sessions_service.get_session(db, s.id).checklist_items) == 1

    sessions_service.remove_slot(db, s.id, slot.id)
    items = sessions_service.consolidate_session(db, s.id)
    assert items == []


def test_consolidate_session_uses_per_recipe_resolved_ingredient(db):
    # M4: the recipe carries a confirmed swap on the ingredient itself
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Salad",
        [{"name": "bulgarian feta", "quantity": 100, "unit": "g",
          "resolved_ingredient": "regular feta"}],
    )
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(db, s.id)
    assert [i.ingredient_name for i in items] == ["regular feta"]


def test_consolidate_session_override_beats_resolved_ingredient(db):
    # a session-only override keys off the DISPLAYED (already-resolved) name and wins for
    # this run only — nothing is written back
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(
        db,
        "Salad",
        [{"name": "bulgarian feta", "quantity": 100, "unit": "g",
          "resolved_ingredient": "regular feta"}],
    )
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))

    items = sessions_service.consolidate_session(
        db, s.id,
        overrides=[SessionOverride(original_name="regular feta", substitute_name="goat cheese")],
    )
    assert [i.ingredient_name for i in items] == ["goat cheese"]

    # the recipe's own data is untouched
    reloaded = recipes_service.get_recipe(db, r.id)
    assert reloaded.ingredients[0].resolved_ingredient == "regular feta"


def test_consolidate_to_taste_item_note(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    r = _recipe_with(db, "Season", [{"name": "saffron", "quantity": 1, "unit": "pinch"}])
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=8))
    items = sessions_service.consolidate_session(db, s.id)
    assert items[0].total_quantity is None
    assert items[0].note == "to taste"

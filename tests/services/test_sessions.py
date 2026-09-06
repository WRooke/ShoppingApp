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

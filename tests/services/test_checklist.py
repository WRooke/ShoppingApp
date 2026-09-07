"""Unit tests for app/services/checklist.py — Phase 5 Chunk 5.3 (load + per-item edits).
AnyList runs in fake mode (seeded milk/eggs/butter on the target list); no network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import anylist_client
from app.services import checklist as checklist_service
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service


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


@pytest.fixture(autouse=True)
def _fake_anylist(monkeypatch):
    monkeypatch.setattr(anylist_client.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_enabled", False, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_target_list_name", "TestList", raising=False)
    anylist_client.reset_client()
    yield
    anylist_client.reset_client()


def _session_with_items(db, ings):
    r = recipes_service.create_recipe(
        db,
        RecipeCreate(
            name="Test", source_type="manual", base_servings=4,
            ingredients=[RecipeIngredientCreate(**i) for i in ings],
        ),
        allow_duplicate=True,
    )
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)
    return s


# --- name matching ------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("milk", "Milk", True),
        ("egg", "eggs", True),
        ("tomato", "tomatoes", True),
        ("beef mince", "  Beef   Mince ", True),
        ("chicken breast", "chicken thigh", False),
        ("glass", "glasses", True),
        ("bass", "bas", False),  # 'ss' not stripped
    ],
)
def test_names_match(a, b, expected):
    assert checklist_service._names_match(a, b) is expected


# --- load -------------------------------------------------------------------


def test_load_raises_when_not_consolidated(db):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    with pytest.raises(checklist_service.ChecklistNotReadyError):
        checklist_service.load_checklist(db, s.id)


def test_load_preticks_items_already_on_the_list(db):
    s = _session_with_items(
        db, [{"name": "milk", "quantity": 1, "unit": "L"},
             {"name": "passata", "quantity": 400, "unit": "g"}]
    )
    items, ok, detail = checklist_service.load_checklist(db, s.id)
    by_name = {i.ingredient_name: i for i in items}
    assert ok is True and detail in (None, "FAKE MODE — no real AnyList call") or ok is True

    assert by_name["milk"].already_on_anylist is True
    assert by_name["milk"].anylist_item_id == "seed-milk"
    assert by_name["milk"].have_it == "yes"  # pre-ticked

    assert by_name["passata"].already_on_anylist is False
    assert by_name["passata"].anylist_item_id is None
    assert by_name["passata"].have_it == "unknown"  # not touched


def test_pretick_never_overrides_a_user_choice(db):
    s = _session_with_items(db, [{"name": "milk", "quantity": 1, "unit": "L"}])
    # user says they don't have it
    milk = s.checklist_items[0]
    milk.have_it = "no"
    db.commit()

    items, _, _ = checklist_service.load_checklist(db, s.id)
    assert items[0].already_on_anylist is True  # still recorded as on the list
    assert items[0].have_it == "no"  # but the user's 'no' is respected


def test_load_when_anylist_disabled_does_not_wipe_match_state(db):
    s = _session_with_items(db, [{"name": "milk", "quantity": 1, "unit": "L"}])
    checklist_service.load_checklist(db, s.id)  # fake mode: sets already_on_anylist + id

    # now disable AnyList entirely (no fake) and reload
    import app.services.anylist_client as ac

    ac.reset_client()
    ac.settings.anylist_fake_mode = False
    ac.settings.anylist_enabled = False
    try:
        items, ok, detail = checklist_service.load_checklist(db, s.id)
    finally:
        ac.settings.anylist_fake_mode = True
        ac.reset_client()

    assert ok is False and detail  # a reason is reported
    assert items[0].already_on_anylist is True  # NOT wiped by the failed fetch
    assert items[0].anylist_item_id == "seed-milk"


# --- edits ----------------------------------------------------------------


def test_update_item_sets_have_it_and_add_to_list(db):
    s = _session_with_items(db, [{"name": "passata", "quantity": 400, "unit": "g"}])
    item_id = s.checklist_items[0].id
    row = checklist_service.update_item(db, s.id, item_id, have_it="no", add_to_list=True)
    assert row.have_it == "no" and row.add_to_list is True


def test_update_item_wrong_session_raises(db):
    s = _session_with_items(db, [{"name": "passata", "quantity": 400, "unit": "g"}])
    with pytest.raises(checklist_service.ChecklistItemNotFoundError):
        checklist_service.update_item(db, s.id + 999, s.checklist_items[0].id, have_it="yes")


def test_resolve_item_commits_a_total_and_clears_the_flag(db):
    s = _session_with_items(
        db, [{"name": "cream", "quantity": 100, "unit": "g"},
             {"name": "cream", "quantity": 200, "unit": "ml"}]
    )
    # consolidation flags the mass+volume mix as needs_review
    cream = next(c for c in s.checklist_items if c.ingredient_name == "cream")
    assert cream.needs_review is True and cream.total_quantity is None

    row = checklist_service.resolve_item(db, s.id, cream.id, total_quantity=300, total_unit="ml")
    assert row.needs_review is False
    assert row.total_quantity == 300 and row.total_unit == "ml"
    assert row.note is None


# --- push (Chunk 5.6) ---------------------------------------------------------


def test_push_adds_needed_items_marks_session_and_writes_history(db):
    from app.models.history import ShoppingHistory

    s = _session_with_items(
        db, [{"name": "milk", "quantity": 1, "unit": "L"},       # on the fake list -> update
             {"name": "passata", "quantity": 400, "unit": "g"},  # not -> add
             {"name": "carrot", "quantity": 3, "unit": None}]    # user has it -> not pushed
    )
    checklist_service.load_checklist(db, s.id)  # sets already_on_anylist for milk
    by_name = {c.ingredient_name: c for c in s.checklist_items}
    checklist_service.update_item(db, s.id, by_name["milk"].id, have_it="no")     # need it
    checklist_service.update_item(db, s.id, by_name["passata"].id, have_it="no")  # need it
    checklist_service.update_item(db, s.id, by_name["carrot"].id, have_it="yes")  # have it

    result = checklist_service.push_to_anylist(db, s.id)
    assert set(result["added"] + result["updated"]) == {"Milk", "Passata"}
    assert "Milk" in result["updated"]  # was already on the (fake) list -> updated in place
    assert result["confirmed"] is True

    db.refresh(s)
    assert s.status == "pushed" and s.pushed_at is not None
    hist = db.query(ShoppingHistory).filter_by(session_id=s.id).one()
    assert hist.id == result["history_id"]
    assert '"Passata"' in hist.items_json

    now_on_list = {i.name for i in anylist_client.get_items()}
    assert "Passata" in now_on_list


def test_push_refuses_a_second_push_without_force(db):
    s = _session_with_items(db, [{"name": "passata", "quantity": 400, "unit": "g"}])
    checklist_service.update_item(db, s.id, s.checklist_items[0].id, have_it="no")
    checklist_service.push_to_anylist(db, s.id)
    with pytest.raises(checklist_service.SessionAlreadyPushedError):
        checklist_service.push_to_anylist(db, s.id)
    # force overrides
    again = checklist_service.push_to_anylist(db, s.id, force=True)
    assert again["session_id"] == s.id


def test_push_includes_and_stamps_selected_usuals(db):
    from app.schemas.usuals import UsualItemCreate
    from app.services import usuals as usuals_service

    soap = usuals_service.create_usual(db, UsualItemCreate(name="dish soap", cadence_days=14))
    s = _session_with_items(db, [{"name": "passata", "quantity": 400, "unit": "g"}])
    checklist_service.update_item(db, s.id, s.checklist_items[0].id, have_it="no")

    result = checklist_service.push_to_anylist(db, s.id, usual_ids=[soap.id])
    assert "dish soap" in result["usuals_added"]
    assert "Dish Soap" in {i.name for i in anylist_client.get_items()}
    db.refresh(soap)
    assert soap.last_added_at is not None  # no longer due


def test_display_quantity_prefers_pack_then_total_then_none(db):
    from app.models.planning import SessionChecklistItem as CI

    assert checklist_service._display_quantity(CI(display_qty="2 × 500g pack", total_quantity=1000, total_unit="g")) == "2 × 500g pack"
    assert checklist_service._display_quantity(CI(total_quantity=400, total_unit="g")) == "400 g"
    assert checklist_service._display_quantity(CI(total_quantity=3, total_unit=None)) == "3"
    assert checklist_service._display_quantity(CI(total_quantity=None, total_unit=None)) is None

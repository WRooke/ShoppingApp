"""A checklist row's decisions (Need it / Have it) must survive the row being renamed.

Chunk 6.7, AnyList push-drop investigation, defect A (docs/anylist-push.md): consolidation keys
rows by ``ingredient_name``, so an alias / merge / substitute used to delete the old row and
create a fresh ``have_it='unknown'`` one — silently dropping a "Need it", after which a name
that happened to match something already on AnyList was pre-ticked "Have it" and never pushed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.planning import SessionChecklistItem
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import anylist_client
from app.services import checklist as checklist_service
from app.services import ingredient_aliases as ingredient_aliases_service
from app.services import recipes as recipes_service
from app.services import session_merges
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
        engine.dispose()


@pytest.fixture(autouse=True)
def _fake_anylist(monkeypatch):
    monkeypatch.setattr(anylist_client.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_enabled", False, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_target_list_name", "TestList", raising=False)
    anylist_client.reset_client()
    yield
    anylist_client.reset_client()


def _session(db, ings):
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


def _row(db, session_id, name):
    return (
        db.query(SessionChecklistItem)
        .filter(SessionChecklistItem.session_id == session_id,
                SessionChecklistItem.ingredient_name == name)
        .first()
    )


def _mark(db, session_id, name, have_it, add_to_list):
    checklist_service.update_item(
        db, session_id, _row(db, session_id, name).id, have_it=have_it, add_to_list=add_to_list
    )


def test_global_alias_added_later_keeps_need_it(db):
    s = _session(db, [{"name": "diced tomato", "quantity": 400, "unit": "g"}])
    _mark(db, s.id, "diced tomato", "no", True)

    ingredient_aliases_service.create_alias(
        db, IngredientAliasCreate(alias_name="diced tomato", canonical_name="canned tomato")
    )
    sessions_service.consolidate_session(db, s.id)

    assert _row(db, s.id, "diced tomato") is None
    renamed = _row(db, s.id, "canned tomato")
    assert (renamed.have_it, renamed.add_to_list) == ("no", True)


def test_session_merge_keeps_need_it(db):
    s = _session(db, [
        {"name": "beef mince", "quantity": 500, "unit": "g"},
        {"name": "minced beef", "quantity": 200, "unit": "g"},
    ])
    _mark(db, s.id, "minced beef", "no", True)

    session_merges.add_session_merge(db, s.id, "minced beef", "beef mince")
    sessions_service.consolidate_session(db, s.id)

    survivor = _row(db, s.id, "beef mince")
    assert (survivor.have_it, survivor.add_to_list) == ("no", True)


def test_substitute_item_keeps_need_it(db):
    s = _session(db, [{"name": "red capsicum", "quantity": 1, "unit": None}])
    _mark(db, s.id, "red capsicum", "no", True)
    item_id = _row(db, s.id, "red capsicum").id

    checklist_service.substitute_item(
        db, s.id, item_id, substitute_name="yellow capsicum",
        original_qty=None, original_unit=None, substitute_qty=None, substitute_unit=None,
        remember=False,
    )

    swapped = _row(db, s.id, "yellow capsicum")
    assert (swapped.have_it, swapped.add_to_list) == ("no", True)


def test_alias_item_keeps_need_it(db):
    s = _session(db, [{"name": "beef mince", "quantity": 500, "unit": "g"}])
    _mark(db, s.id, "beef mince", "no", True)
    item_id = _row(db, s.id, "beef mince").id

    checklist_service.alias_item(db, s.id, item_id, alias_name="ground beef", remember=True)

    # alias_item folds the typed name INTO this row, so this row survives untouched ...
    assert _row(db, s.id, "beef mince").have_it == "no"


def test_alias_renaming_the_row_itself_keeps_need_it(db):
    # the other direction: this row's own name becomes an alias of a different canonical name
    s = _session(db, [{"name": "ground beef", "quantity": 500, "unit": "g"}])
    _mark(db, s.id, "ground beef", "no", True)
    ingredient_aliases_service.create_alias(
        db, IngredientAliasCreate(alias_name="ground beef", canonical_name="beef mince")
    )
    sessions_service.consolidate_session(db, s.id)

    row = _row(db, s.id, "beef mince")
    assert (row.have_it, row.add_to_list) == ("no", True)


def test_survivor_is_never_downgraded_by_a_weaker_stale_row(db):
    s = _session(db, [
        {"name": "beef mince", "quantity": 500, "unit": "g"},
        {"name": "minced beef", "quantity": 200, "unit": "g"},
    ])
    _mark(db, s.id, "beef mince", "no", True)
    _mark(db, s.id, "minced beef", "yes", False)

    session_merges.add_session_merge(db, s.id, "minced beef", "beef mince")
    sessions_service.consolidate_session(db, s.id)

    survivor = _row(db, s.id, "beef mince")
    assert (survivor.have_it, survivor.add_to_list) == ("no", True)


def test_a_stronger_stale_row_upgrades_a_weaker_survivor(db):
    s = _session(db, [
        {"name": "beef mince", "quantity": 500, "unit": "g"},
        {"name": "minced beef", "quantity": 200, "unit": "g"},
    ])
    _mark(db, s.id, "beef mince", "yes", False)
    _mark(db, s.id, "minced beef", "no", True)

    session_merges.add_session_merge(db, s.id, "minced beef", "beef mince")
    sessions_service.consolidate_session(db, s.id)

    survivor = _row(db, s.id, "beef mince")
    assert (survivor.have_it, survivor.add_to_list) == ("no", True)


def test_a_row_whose_ingredient_really_disappeared_is_dropped(db):
    s = _session(db, [{"name": "salt", "quantity": 1, "unit": "tsp"}])
    # a decided row for an ingredient that is no longer in any recipe
    db.add(SessionChecklistItem(
        session_id=s.id, ingredient_name="pepper", have_it="no", add_to_list=True
    ))
    db.commit()

    sessions_service.consolidate_session(db, s.id)

    assert _row(db, s.id, "pepper") is None
    assert _row(db, s.id, "salt") is not None


def test_renamed_row_matching_something_on_anylist_is_not_downgraded_to_have_it(db):
    # the exact failure chain from the prod investigation: a row decided "Need it" is renamed,
    # the NEW name matches an ACTIVE item already on AnyList ('milk' is seeded active on the fake
    # list; its seeded 'butter' is crossed off, which no longer counts as "on the list"), and
    # load_checklist pre-ticks any 'unknown' row to "Have it" — so it was never pushed
    s = _session(db, [{"name": "whole milk", "quantity": 1, "unit": "l"}])
    _mark(db, s.id, "whole milk", "no", True)

    ingredient_aliases_service.create_alias(
        db, IngredientAliasCreate(alias_name="whole milk", canonical_name="milk")
    )

    items, ok, _detail, _breakdown = checklist_service.load_checklist(db, s.id)

    assert ok
    milk = next(i for i in items if i.ingredient_name == "milk")
    assert milk.already_on_anylist is True
    assert (milk.have_it, milk.add_to_list) == ("no", True)  # NOT pre-ticked to "yes"

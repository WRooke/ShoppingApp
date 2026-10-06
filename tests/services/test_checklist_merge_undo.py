"""Checklist merge: what "every time" records, and Undo (Chunk 6.7, 2026-10-06 — the toast that
replaced the native confirm()). docs/ui-ux.md > no native dialogs; docs/ingredient-handling.md."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.catalog import IngredientAlias
from app.models.planning import SessionChecklistItem, SessionIngredientMerge
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import anylist_client
from app.services import checklist as cl
from app.services import ingredient_aliases as ia
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setattr(anylist_client.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_enabled", False, raising=False)
    anylist_client.reset_client()
    yield
    anylist_client.reset_client()


def _session(db):
    r = recipes_service.create_recipe(
        db,
        RecipeCreate(name="R", source_type="manual", base_servings=4, ingredients=[
            RecipeIngredientCreate(name="parmesan", quantity=35, unit="g"),
            RecipeIngredientCreate(name="pecorino", quantity=20, unit="g"),
            RecipeIngredientCreate(name="pork tenderloin", quantity=600, unit="g"),
        ]),
        allow_duplicate=True,
    )
    s = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)
    return s


def _row(db, sid, name):
    return (db.query(SessionChecklistItem)
            .filter(SessionChecklistItem.session_id == sid, SessionChecklistItem.ingredient_name == name).first())


def _need(db, sid, name):
    cl.update_item(db, sid, _row(db, sid, name).id, have_it="no", add_to_list=True)


def test_merge_every_time_records_where_the_alias_came_from_and_reports_its_ids(db):
    s = _session(db)
    ids: list[int] = []
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=True,
                   created_alias_ids=ids)
    alias = db.query(IngredientAlias).one()
    assert (alias.alias_name, alias.canonical_name, alias.source) == ("pecorino", "parmesan", "merge")
    assert ids == [alias.id]


def test_aliases_made_by_hand_stay_source_user_and_clients_cannot_choose_the_source(db):
    row = ia.create_alias(db, IngredientAliasCreate(alias_name="a", canonical_name="b"))
    assert row.source == "user"
    assert "source" not in IngredientAliasCreate.model_fields  # the API cannot set it
    with pytest.raises(ValueError):
        ia.create_alias(db, IngredientAliasCreate(alias_name="c", canonical_name="d"), source="system")


def test_undo_of_a_this_list_only_merge_restores_both_lines_with_the_decision(db):
    s = _session(db)
    _need(db, s.id, "pecorino")
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=False)
    assert _row(db, s.id, "pecorino") is None
    assert (_row(db, s.id, "parmesan").have_it, _row(db, s.id, "parmesan").add_to_list) == ("no", True)

    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"])

    assert db.query(SessionIngredientMerge).count() == 0
    back = _row(db, s.id, "pecorino")
    assert back is not None and (back.have_it, back.add_to_list) == ("no", True)  # the decision survived
    assert _row(db, s.id, "parmesan") is not None


def test_undo_of_a_merge_every_time_deletes_the_alias_and_restores_the_lines(db):
    s = _session(db)
    _need(db, s.id, "parmesan")
    ids: list[int] = []
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=True,
                   created_alias_ids=ids)
    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"], alias_ids=ids)

    assert db.query(IngredientAlias).count() == 0
    assert _row(db, s.id, "pecorino") is not None
    assert _row(db, s.id, "pecorino").add_to_list is True  # inherits the merged line's decision
    assert _row(db, s.id, "parmesan").add_to_list is True


def test_undo_is_idempotent_and_tolerates_an_alias_already_deleted_in_settings(db):
    s = _session(db)
    ids: list[int] = []
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=True,
                   created_alias_ids=ids)
    ia.delete_alias(db, ids[0])  # removed in Settings in the meantime
    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"], alias_ids=ids)
    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"], alias_ids=ids)  # again
    assert _row(db, s.id, "pecorino") is not None and _row(db, s.id, "parmesan") is not None


def test_undo_never_overwrites_a_decision_made_on_a_restored_line_after_the_merge(db):
    s = _session(db)
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=False)
    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"])
    cl.update_item(db, s.id, _row(db, s.id, "pecorino").id, have_it="yes")
    cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"])  # second undo: no-op
    assert _row(db, s.id, "pecorino").have_it == "yes"


def test_undo_is_refused_once_the_session_is_pushed(db):
    s = _session(db)
    cl.merge_items(db, s.id, item_names=["parmesan", "pecorino"], canonical_name="parmesan", remember=False)
    sessions_service.get_session(db, s.id).status = "pushed"
    db.commit()
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.undo_merge(db, s.id, canonical_name="parmesan", member_names=["pecorino"])

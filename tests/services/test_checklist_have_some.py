"""Checklist "I have some" (Chunk 6.7, user-feedback batch, polish batch 3, item D): an amount already at home reduces
what is bought, without ever changing what the recipes need (docs/checklist-and-shopping.md).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.catalog import ProductUnit
from app.models.planning import SessionChecklistItem
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.services import checklist as checklist_service
from app.services import have_some
from app.services import ingredient_aliases as ingredient_aliases_service
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
        engine.dispose()


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


def _row(db, s, name):
    return next(c for c in sessions_service.get_session(db, s.id).checklist_items if c.ingredient_name == name)


@pytest.mark.parametrize(
    "total, unit, have, have_unit, expected",
    [
        (3, None, 1, None, 2),
        (3, None, 5, None, 0),        # never negative
        (500, "g", 200, "G ", 300),   # unit compare ignores case / spaces
        (500, "g", 200, "ml", 500),   # unit mismatch -> buy everything
        (3, None, None, None, 3),
        (None, None, 1, None, None),  # no numeric total (coarse / to taste)
    ],
)
def test_amount_to_buy(total, unit, have, have_unit, expected):
    assert have_some.amount_to_buy(total, unit, have, have_unit) == expected


def test_set_have_some_reduces_what_is_bought_but_not_what_is_needed(db):
    s = _session(db, [{"name": "tomato", "quantity": 3, "unit": None}])
    row = _row(db, s, "tomato")
    checklist_service.set_have_some(db, s.id, row.id, quantity=1)
    row = _row(db, s, "tomato")
    assert row.total_quantity == 3 and row.have_quantity == 1
    assert checklist_service._anylist_quantity(row) == "2"
    assert row.have_it == "unknown"  # partial amounts don't flip the decision


def test_have_some_survives_reconsolidation(db):
    s = _session(db, [{"name": "tomato", "quantity": 3, "unit": None}])
    checklist_service.set_have_some(db, s.id, _row(db, s, "tomato").id, quantity=1)
    sessions_service.consolidate_session(db, s.id)
    assert _row(db, s, "tomato").have_quantity == 1


def test_having_enough_becomes_have_it(db):
    s = _session(db, [{"name": "tomato", "quantity": 3, "unit": None}])
    row = _row(db, s, "tomato")
    checklist_service.update_item(db, s.id, row.id, have_it="no", add_to_list=True)
    checklist_service.set_have_some(db, s.id, row.id, quantity=3)
    row = _row(db, s, "tomato")
    assert row.have_it == "yes" and row.add_to_list is False


def test_zero_clears_and_keeps_the_decision(db):
    s = _session(db, [{"name": "tomato", "quantity": 3, "unit": None}])
    row = _row(db, s, "tomato")
    checklist_service.update_item(db, s.id, row.id, have_it="no", add_to_list=True)
    checklist_service.set_have_some(db, s.id, row.id, quantity=1)
    checklist_service.set_have_some(db, s.id, row.id, quantity=0)
    row = _row(db, s, "tomato")
    assert row.have_quantity is None and row.have_it == "no"


def test_packs_are_counted_on_the_amount_still_to_buy(db):
    db.add(ProductUnit(ingredient_name="flour", purchase_label="500g bag", purchase_qty=500, purchase_unit="g"))
    db.commit()
    s = _session(db, [{"name": "flour", "quantity": 900, "unit": "g"}])
    row = _row(db, s, "flour")
    assert "2" in (row.display_qty or "")
    checklist_service.set_have_some(db, s.id, row.id, quantity=450)
    row = _row(db, s, "flour")
    assert row.display_qty and "2" not in row.display_qty.split("×")[0]  # 450 g -> one bag


def test_not_offered_without_a_single_amount(db):
    # a mass + volume mix is an unresolved conflict: no single unit to subtract in
    s = _session(db, [{"name": "cream", "quantity": 100, "unit": "g"},
                      {"name": "cream", "quantity": 200, "unit": "ml"}])
    with pytest.raises(checklist_service.HaveSomeNotApplicableError):
        checklist_service.set_have_some(db, s.id, _row(db, s, "cream").id, quantity=1)


def test_have_amounts_add_up_when_rows_fold_together(db):
    s = _session(db, [
        {"name": "lemon juice", "quantity": 2, "unit": None},
        {"name": "lemon", "quantity": 3, "unit": None},
    ])
    checklist_service.set_have_some(db, s.id, _row(db, s, "lemon juice").id, quantity=1)
    checklist_service.set_have_some(db, s.id, _row(db, s, "lemon").id, quantity=1)
    ingredient_aliases_service.create_alias(
        db, IngredientAliasCreate(alias_name="lemon juice", canonical_name="lemon")
    )
    sessions_service.consolidate_session(db, s.id)
    assert _row(db, s, "lemon").have_quantity == 2

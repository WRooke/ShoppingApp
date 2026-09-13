"""Unit tests for app/services/coarse_ingredients.py — ingredients that skip quantity/unit
math entirely at consolidation (2026-09-12, see CLAUDE.md > Ingredient Unit Handling >
Layer D). Consolidation wiring (counting slots, computing packs_needed) is tested alongside
session_consolidation.py, not here — this file is CRUD only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.coarse_ingredients import CoarseIngredientCreate, CoarseIngredientUpdate
from app.services import coarse_ingredients as ci


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
        # 2026-09-13 code review — engine.dispose() (not just session.close()) is
        # required for an in-memory SQLite engine: SQLAlchemy's SingletonThreadPool
        # keeps the underlying sqlite3.Connection open until the engine itself is
        # disposed, so without this it's only released whenever the garbage collector
        # happens to run -- which pytest's own unraisable-exception check (via an
        # explicit gc.collect()) turns into a `ResourceWarning: unclosed database`
        # attributed to some unrelated, later test. See pytest.ini's `filterwarnings
        # = error` and CLAUDE.md > Code Architecture > "keep comments true".
        session.close()
        engine.dispose()


def test_create_defaults_recipes_per_pack_to_3(db):
    row = ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="Parsley"))
    assert row.name == "parsley"
    assert row.recipes_per_pack == 3
    assert row.purchase_label is None


def test_create_with_explicit_pack_label_and_divisor(db):
    row = ci.create_coarse_ingredient(
        db, CoarseIngredientCreate(name="coriander", purchase_label="bunch", recipes_per_pack=2)
    )
    assert (row.purchase_label, row.recipes_per_pack) == ("bunch", 2)


def test_create_duplicate_name_raises(db):
    ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="mint"))
    with pytest.raises(ci.DuplicateCoarseIngredientError):
        ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="Mint"))


def test_list_orders_by_name(db):
    ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="parsley"))
    ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="basil"))
    rows, total = ci.list_coarse_ingredients(db)
    assert total == 2
    assert [r.name for r in rows] == ["basil", "parsley"]


def test_update_can_change_label_and_divisor(db):
    row = ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="basil"))
    ci.update_coarse_ingredient(
        db, row.id, CoarseIngredientUpdate(purchase_label="bunch", recipes_per_pack=4)
    )
    assert (row.purchase_label, row.recipes_per_pack) == ("bunch", 4)


def test_update_can_clear_purchase_label(db):
    row = ci.create_coarse_ingredient(
        db, CoarseIngredientCreate(name="basil", purchase_label="bunch")
    )
    ci.update_coarse_ingredient(db, row.id, CoarseIngredientUpdate(purchase_label=None))
    assert row.purchase_label is None


def test_update_not_found(db):
    with pytest.raises(ci.CoarseIngredientNotFoundError):
        ci.update_coarse_ingredient(db, 999, CoarseIngredientUpdate(purchase_label="bunch"))


def test_delete_only_removes_that_row(db):
    a = ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="parsley"))
    b = ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="basil"))
    ci.delete_coarse_ingredient(db, a.id)
    remaining, total = ci.list_coarse_ingredients(db)
    assert total == 1
    assert remaining[0].id == b.id


def test_coarse_map_keyed_by_name(db):
    ci.create_coarse_ingredient(db, CoarseIngredientCreate(name="parsley", purchase_label="bunch"))
    m = ci.coarse_map(db)
    assert set(m) == {"parsley"}
    assert m["parsley"].purchase_label == "bunch"


def test_coarse_map_empty_when_no_rows(db):
    assert ci.coarse_map(db) == {}

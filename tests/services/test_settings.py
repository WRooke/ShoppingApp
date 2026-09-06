"""Unit tests for app/services/settings.py — exercised directly against a DB
session, no FastAPI/HTTP involved (see CLAUDE.md > Code Architecture &
Maintainability). Router-level behaviour is covered separately by
tests/routers/test_settings.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.settings import (
    ProductUnitCreate,
    ProductUnitUpdate,
    StapleCreate,
    StapleUpdate,
)
from app.services import settings as settings_service


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


# --- staples ---------------------------------------------------------------


def test_create_staple_normalises_name(db):
    staple = settings_service.create_staple(db, StapleCreate(name="  Salt  "))

    assert staple.id is not None
    assert staple.name == "salt"


def test_create_staple_duplicate_name_raises(db):
    settings_service.create_staple(db, StapleCreate(name="salt"))

    with pytest.raises(settings_service.DuplicateStapleNameError):
        settings_service.create_staple(db, StapleCreate(name="Salt"))


def test_list_staples_ordered_by_name(db):
    settings_service.create_staple(db, StapleCreate(name="vegetable oil"))
    settings_service.create_staple(db, StapleCreate(name="black pepper"))

    results, total = settings_service.list_staples(db)

    assert total == 2
    assert [s.name for s in results] == ["black pepper", "vegetable oil"]


def test_update_staple_partial_update_only_touches_sent_fields(db):
    staple = settings_service.create_staple(db, StapleCreate(name="salt"))

    updated = settings_service.update_staple(db, staple.id, StapleUpdate(notes="fine sea salt"))

    assert updated.name == "salt"  # untouched
    assert updated.notes == "fine sea salt"


def test_update_staple_raises_when_missing(db):
    with pytest.raises(settings_service.StapleNotFoundError):
        settings_service.update_staple(db, 999, StapleUpdate(notes="x"))


def test_update_staple_duplicate_name_raises(db):
    settings_service.create_staple(db, StapleCreate(name="salt"))
    other = settings_service.create_staple(db, StapleCreate(name="pepper"))

    with pytest.raises(settings_service.DuplicateStapleNameError):
        settings_service.update_staple(db, other.id, StapleUpdate(name="salt"))


def test_delete_staple_removes_row(db):
    staple = settings_service.create_staple(db, StapleCreate(name="salt"))

    settings_service.delete_staple(db, staple.id)

    results, total = settings_service.list_staples(db)
    assert total == 0
    assert results == []


def test_delete_staple_raises_when_missing(db):
    with pytest.raises(settings_service.StapleNotFoundError):
        settings_service.delete_staple(db, 999)


# --- product_units -----------------------------------------------------


def _make_product_unit(**overrides) -> ProductUnitCreate:
    payload = {
        "ingredient_name": "  Eggs  ",
        "purchase_label": "dozen",
        "purchase_qty": 12,
        "purchase_unit": "each",
    }
    payload.update(overrides)
    return ProductUnitCreate(**payload)


def test_create_product_unit_normalises_name_and_defaults_not_preseeded(db):
    unit = settings_service.create_product_unit(db, _make_product_unit())

    assert unit.id is not None
    assert unit.ingredient_name == "eggs"
    assert unit.is_preseeded is False


def test_create_product_unit_duplicate_ingredient_name_raises(db):
    settings_service.create_product_unit(db, _make_product_unit())

    with pytest.raises(settings_service.DuplicateProductUnitNameError):
        settings_service.create_product_unit(db, _make_product_unit(purchase_label="half-dozen"))


def test_list_product_units_ordered_by_ingredient_name(db):
    settings_service.create_product_unit(db, _make_product_unit(ingredient_name="milk"))
    settings_service.create_product_unit(db, _make_product_unit(ingredient_name="butter"))

    results, total = settings_service.list_product_units(db)

    assert total == 2
    assert [u.ingredient_name for u in results] == ["butter", "milk"]


def test_update_product_unit_partial_update(db):
    unit = settings_service.create_product_unit(db, _make_product_unit())

    updated = settings_service.update_product_unit(
        db, unit.id, ProductUnitUpdate(purchase_qty=6)
    )

    assert updated.purchase_qty == 6
    assert updated.purchase_label == "dozen"  # untouched


def test_update_product_unit_raises_when_missing(db):
    with pytest.raises(settings_service.ProductUnitNotFoundError):
        settings_service.update_product_unit(db, 999, ProductUnitUpdate(purchase_qty=1))


def test_delete_product_unit_removes_row(db):
    unit = settings_service.create_product_unit(db, _make_product_unit())

    settings_service.delete_product_unit(db, unit.id)

    results, total = settings_service.list_product_units(db)
    assert total == 0
    assert results == []


def test_delete_product_unit_raises_when_missing(db):
    with pytest.raises(settings_service.ProductUnitNotFoundError):
        settings_service.delete_product_unit(db, 999)


def test_get_section_vocabulary_returns_the_canonical_list():
    from app.seed_data import SECTION_VOCABULARY

    assert settings_service.get_section_vocabulary() == SECTION_VOCABULARY

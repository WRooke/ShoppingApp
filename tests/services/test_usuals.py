"""Unit tests for app/services/usuals.py — "the usuals" (Phase 5 Chunk 5.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.usuals import UsualItemCreate, UsualItemUpdate
from app.services import usuals as u


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


def _c(name, cadence=14, notes=None):
    return UsualItemCreate(name=name, cadence_days=cadence, notes=notes)


def test_create_normalises_name(db):
    item = u.create_usual(db, _c("  Laundry   Powder "))
    assert item.name == "laundry powder"
    assert item.cadence_days == 14
    assert item.last_added_at is None


def test_duplicate_name_raises(db):
    u.create_usual(db, _c("dish soap"))
    with pytest.raises(u.DuplicateUsualItemNameError):
        u.create_usual(db, _c("Dish Soap"))


def test_get_missing_raises(db):
    with pytest.raises(u.UsualItemNotFoundError):
        u.get_usual(db, 999)


def test_update_and_rename_collision(db):
    a = u.create_usual(db, _c("a"))
    b = u.create_usual(db, _c("b"))
    u.update_usual(db, a.id, UsualItemUpdate(cadence_days=30, notes="monthly-ish"))
    assert u.get_usual(db, a.id).cadence_days == 30
    with pytest.raises(u.DuplicateUsualItemNameError):
        u.update_usual(db, b.id, UsualItemUpdate(name="A"))


def test_delete(db):
    item = u.create_usual(db, _c("bin bags"))
    u.delete_usual(db, item.id)
    with pytest.raises(u.UsualItemNotFoundError):
        u.get_usual(db, item.id)


# --- due logic ---------------------------------------------------------------


def test_never_added_is_due(db):
    item = u.create_usual(db, _c("paper towels", cadence=7))
    assert u.is_due(item) is True


def test_recently_added_is_not_due(db):
    item = u.create_usual(db, _c("paper towels", cadence=7))
    now = datetime(2026, 9, 7, 12, 0, 0)
    item.last_added_at = now - timedelta(days=3)
    db.commit()
    assert u.is_due(item, as_of=now) is False


def test_cadence_elapsed_is_due(db):
    item = u.create_usual(db, _c("paper towels", cadence=7))
    now = datetime(2026, 9, 7, 12, 0, 0)
    item.last_added_at = now - timedelta(days=8)
    db.commit()
    assert u.is_due(item, as_of=now) is True


def test_due_items_filters_and_orders(db):
    now = datetime(2026, 9, 7, 12, 0, 0)
    fresh = u.create_usual(db, _c("zebra cleaner", cadence=30))
    fresh.last_added_at = now - timedelta(days=1)
    stale = u.create_usual(db, _c("apple juice", cadence=7))
    stale.last_added_at = now - timedelta(days=10)
    u.create_usual(db, _c("mystery", cadence=7))  # never added -> due
    db.commit()

    due = u.due_items(db, as_of=now)
    assert [d.name for d in due] == ["apple juice", "mystery"]  # zebra cleaner not due; name order


def test_mark_added_stamps_and_ignores_unknown_ids(db):
    a = u.create_usual(db, _c("a"))
    when = datetime(2026, 9, 7, 9, 0, 0)
    u.mark_added(db, [a.id, 123456], when=when)
    assert u.get_usual(db, a.id).last_added_at == when


def test_due_as_checklist_rows_shape(db):
    u.create_usual(db, _c("soap", cadence=5, notes="the good one"))
    rows = u.due_as_checklist_rows(db)
    assert len(rows) == 1
    assert rows[0].name == "soap" and rows[0].cadence_days == 5 and rows[0].add_to_list is False

"""Unit tests for app/services/usuals.py — "the usuals" (Phase 5 Chunk 5.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_update_can_explicitly_clear_notes(db):
    """2026-09-13 code review: update_usual() used to guard every assignment with
    `if value is not None`, which silently discarded an explicit `{"notes": null}` meant to
    clear a previously-set note — exclude_unset=True already limits `changes` to fields
    actually sent, so that guard was pure data loss, not a safety net."""
    item = u.create_usual(db, _c("dish soap", notes="the good brand"))
    assert item.notes == "the good brand"
    updated = u.update_usual(db, item.id, UsualItemUpdate(notes=None))
    assert updated.notes is None


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
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    item.last_added_at = now - timedelta(days=3)
    db.commit()
    assert u.is_due(item, as_of=now) is False


def test_cadence_elapsed_is_due(db):
    item = u.create_usual(db, _c("paper towels", cadence=7))
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    item.last_added_at = now - timedelta(days=8)
    db.commit()
    assert u.is_due(item, as_of=now) is True


def test_is_due_coerces_a_naive_as_of_to_aware_utc(db):
    """Defence in depth (2026-09-19 checklist-500 fix): is_due()/due_items()/mark_added() must
    not blow up on `TypeError: can't compare offset-naive and offset-aware datetimes` even if
    a caller hands them a naive `as_of` directly — see app.services.usuals._ensure_aware()."""
    item = u.create_usual(db, _c("paper towels", cadence=7))
    aware_now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    item.last_added_at = aware_now - timedelta(days=3)
    db.commit()

    naive_now = datetime(2026, 9, 7, 12, 0, 0)  # no tzinfo
    assert u.is_due(item, as_of=naive_now) is False


def test_is_due_tolerates_a_null_cadence():
    """Defensive hardening, not a confirmed live path — cadence_days is nullable=False in the
    schema, so a NULL can't be committed through normal means. But is_due() is a plain
    function with no DB access of its own; guarding it costs nothing and matches the same
    "never trust a row's shape past the DB boundary" caution applied to
    SessionChecklistItem.review_options (app/models/planning.py) after the 2026-09-17
    checklist-500 investigation."""
    from app.models.catalog import UsualItem

    item = UsualItem(name="mystery", cadence_days=None)
    assert u.is_due(item) is True


def test_due_items_filters_and_orders(db):
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
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
    when = datetime(2026, 9, 7, 9, 0, 0, tzinfo=timezone.utc)
    u.mark_added(db, [a.id, 123456], when=when)
    assert u.get_usual(db, a.id).last_added_at == when


# --- 2026-09-19 checklist-500 regression -------------------------------------


def test_mark_added_then_due_items_survives_a_db_round_trip(db):
    """Reproduces the exact production crash: mark_added() with no explicit `when` (the
    `utcnow()` fallback, aware), committed, then re-fetched fresh from the DB (as every real
    request does via a new Session) and compared in due_items()/is_due() with no explicit
    `as_of` (also the `utcnow()` fallback). Before the UTCDateTime column type fix, the
    re-fetched `last_added_at` came back naive and this raised `TypeError: can't compare
    offset-naive and offset-aware datetimes` — see GET /api/v1/checklist/{id}, app.log
    2026-09-19 20:22-20:23."""
    frequent = u.create_usual(db, _c("paper towels", cadence=7))
    rare = u.create_usual(db, _c("light bulbs", cadence=365))

    u.mark_added(db, [frequent.id, rare.id])  # no `when` -> utcnow() fallback, aware
    db.commit()
    db.expire_all()  # force the next access to re-fetch from SQLite, like a fresh request would

    due = u.due_items(db)  # no `as_of` -> utcnow() fallback, aware
    assert [d.name for d in due] == []  # both just added, neither due yet

    # Push "paper towels" 8 days into its 7-day cadence by rewriting its stamp directly (still
    # exercises the same naive-vs-aware round trip on the comparison side).
    stale_stamp = datetime.now(timezone.utc) - timedelta(days=8)
    u.mark_added(db, [frequent.id], when=stale_stamp)
    db.commit()
    db.expire_all()

    due_names = [d.name for d in u.due_items(db)]
    assert due_names == ["paper towels"]
    assert u.is_due(u.get_usual(db, rare.id)) is False


def test_due_as_checklist_rows_shape(db):
    u.create_usual(db, _c("soap", cadence=5, notes="the good one"))
    rows = u.due_as_checklist_rows(db)
    assert len(rows) == 1
    assert rows[0].name == "soap" and rows[0].cadence_days == 5 and rows[0].add_to_list is False

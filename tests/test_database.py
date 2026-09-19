"""Unit tests for app/database.py's ``UTCDateTime`` type.

Regression coverage for the 2026-09-19 checklist 500: a plain ``Column(DateTime)`` stores an
aware Python datetime as an offset-less string on SQLite and returns it **naive** on the next
fetch, silently dropping tzinfo. ``UTCDateTime`` closes that gap. These tests exercise a real
round trip through an actual engine (commit + expire + re-fetch) — an in-memory-only assertion
wouldn't catch this, which is exactly why the original bug shipped (see
tests/services/test_usuals.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.database import Base, UTCDateTime


class _ProbeBase(DeclarativeBase):
    """Deliberately NOT ``app.database.Base`` — registering a probe-only table on the real
    ``Base`` would leak it into ``Base.metadata`` for the rest of the test session (module
    import registers ORM classes permanently), which broke
    tests/test_migrations.py's create_all()-vs-alembic parity check the first time this was
    tried (it started seeing an extra table). Its tables are created into the same engine as
    ``Base``'s below, just from separate metadata."""


class _Stamped(_ProbeBase):
    __tablename__ = "_utc_datetime_probe"

    id = Column(Integer, primary_key=True)
    stamp = Column(UTCDateTime(), nullable=True)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401 — registers every real model on Base.metadata

    Base.metadata.create_all(bind=engine)
    _ProbeBase.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        # engine.dispose() (not just session.close()) is required for an in-memory SQLite
        # engine — see tests/services/test_usuals.py's `db` fixture for the full rationale.
        session.close()
        engine.dispose()


def _refetch(db, row_id: int) -> _Stamped:
    db.expire_all()
    return db.get(_Stamped, row_id)


def test_aware_utc_round_trips_as_aware_utc(db):
    original = datetime(2026, 9, 19, 20, 22, 33, tzinfo=timezone.utc)
    row = _Stamped(stamp=original)
    db.add(row)
    db.commit()

    fetched = _refetch(db, row.id)
    assert fetched.stamp.tzinfo == timezone.utc
    assert fetched.stamp == original


def test_aware_non_utc_normalises_to_correct_utc_instant(db):
    plus_ten = timezone(timedelta(hours=10))
    original = datetime(2026, 9, 20, 6, 22, 33, tzinfo=plus_ten)  # same instant as the UTC test
    row = _Stamped(stamp=original)
    db.add(row)
    db.commit()

    fetched = _refetch(db, row.id)
    assert fetched.stamp.tzinfo == timezone.utc
    assert fetched.stamp == original
    assert fetched.stamp == datetime(2026, 9, 19, 20, 22, 33, tzinfo=timezone.utc)


def test_naive_input_is_assumed_utc_and_comes_back_aware(db):
    naive = datetime(2026, 9, 19, 20, 22, 33)
    row = _Stamped(stamp=naive)
    db.add(row)
    db.commit()

    fetched = _refetch(db, row.id)
    assert fetched.stamp.tzinfo == timezone.utc
    assert fetched.stamp == naive.replace(tzinfo=timezone.utc)


def test_null_round_trips_as_none(db):
    row = _Stamped(stamp=None)
    db.add(row)
    db.commit()

    fetched = _refetch(db, row.id)
    assert fetched.stamp is None


def test_column_default_and_onupdate_round_trip_as_aware_utc(db):
    """Every real model sets its timestamp columns via `default=utcnow`/`onupdate=utcnow`
    (app/models/*.py), never an explicit value at call time — a plain probe row that always
    sets `stamp` directly (the tests above) wouldn't catch a divergence in how SQLAlchemy
    binds a *default-supplied* value vs an explicit one. Exercise the real path against an
    actual model instead of the synthetic `_Stamped` table."""
    from app.models.catalog import Staple

    row = Staple(name="zz-utcdatetime-default-probe")
    db.add(row)
    db.commit()  # created_at/updated_at populated via default=utcnow, not set here

    fetched_id = row.id
    db.expire_all()
    fetched = db.get(Staple, fetched_id)
    assert fetched.created_at.tzinfo == timezone.utc
    assert fetched.updated_at.tzinfo == timezone.utc

    fetched.notes = "trigger onupdate"
    db.commit()  # updated_at repopulated via onupdate=utcnow
    db.expire_all()
    reloaded = db.get(Staple, fetched_id)
    assert reloaded.updated_at.tzinfo == timezone.utc
    assert reloaded.updated_at >= reloaded.created_at

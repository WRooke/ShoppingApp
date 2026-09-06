"""Unit tests for app/services/substitutions.py — the remembered-substitutions quick-pick
library (Phase 3.9 M4). No `is_default`, no auto-apply — a row only ever pre-fills a
per-recipe confirm UI.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.substitutions import (
    RememberedSubstitutionCreate,
    RememberedSubstitutionUpdate,
)
from app.services import substitutions as subs


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


def _c(original, substitute, note=None):
    return RememberedSubstitutionCreate(
        original_name=original, substitute_name=substitute, note=note
    )


def test_create_normalises_names_and_sets_last_used(db):
    row = subs.create_substitution(db, _c("  Bulgarian Feta ", "Regular  Feta", note="close enough"))
    assert row.original_name == "bulgarian feta"
    assert row.substitute_name == "regular feta"
    assert row.note == "close enough"
    assert row.last_used_at is not None


def test_multiple_substitutes_per_original_all_allowed_no_default(db):
    a = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    b = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    assert a.id != b.id
    assert not hasattr(a, "is_default")


def test_duplicate_pair_raises(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    with pytest.raises(subs.DuplicateSubstitutionError):
        subs.create_substitution(db, _c("Bulgarian Feta", "Regular Feta"))


def test_self_substitution_rejected(db):
    with pytest.raises(subs.InvalidSubstitutionError):
        subs.create_substitution(db, _c("feta", "feta"))


def test_update_substitute_name_and_note(db):
    row = subs.create_substitution(db, _c("bulgarian feta", "regular feta", note="a"))
    updated = subs.update_substitution(
        db, row.id, RememberedSubstitutionUpdate(substitute_name="goat cheese", note="  b  ")
    )
    assert updated.substitute_name == "goat cheese" and updated.note == "b"


def test_update_substitute_name_collision_raises(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    other = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    with pytest.raises(subs.DuplicateSubstitutionError):
        subs.update_substitution(
            db, other.id, RememberedSubstitutionUpdate(substitute_name="regular feta")
        )


def test_delete(db):
    row = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    subs.delete_substitution(db, row.id)
    with pytest.raises(subs.SubstitutionNotFoundError):
        subs.get_substitution(db, row.id)


def test_list_ordered_by_original_then_most_recent(db):
    subs.create_substitution(db, _c("apple", "pear"))
    older = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    newer = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    subs.touch(db, original_name="bulgarian feta", substitute_name="regular feta")  # older -> most recent

    rows, total = subs.list_substitutions(db)
    assert total == 3
    assert [r.original_name for r in rows] == ["apple", "bulgarian feta", "bulgarian feta"]
    assert rows[1].substitute_name == "regular feta"  # touched -> floats to top of its group
    assert rows[2].substitute_name == "goat cheese"
    _ = (older, newer)


def test_quick_picks_for(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    subs.create_substitution(db, _c("banana shallot", "eschalot"))

    picks = subs.quick_picks_for(db, "  Bulgarian Feta ")
    assert {p.substitute_name for p in picks} == {"regular feta", "goat cheese"}
    assert subs.quick_picks_for(db, "nothing here") == []


def test_touch_is_silent_noop_for_unknown_pair(db):
    subs.touch(db, original_name="ghost", substitute_name="phantom")  # no row, no error

"""Unit tests for app/services/substitutions.py — direct DB session, no HTTP.
See CLAUDE.md > Ingredient Substitution.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.substitutions import (
    IngredientSubstitutionCreate,
    IngredientSubstitutionUpdate,
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


def _c(original, substitute, is_default=False):
    return IngredientSubstitutionCreate(
        original_name=original, substitute_name=substitute, is_default=is_default
    )


def test_first_substitute_is_forced_default_and_names_normalised(db):
    row = subs.create_substitution(db, _c("  Bulgarian Feta ", "Regular  Feta", is_default=False))
    assert row.original_name == "bulgarian feta"
    assert row.substitute_name == "regular feta"
    assert row.is_default is True  # forced — first for this original


def test_second_substitute_non_default_unless_asked(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    second = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    assert second.is_default is False


def test_new_default_demotes_the_old_one(db):
    first = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    second = subs.create_substitution(db, _c("bulgarian feta", "goat cheese", is_default=True))

    db.refresh(first)
    assert first.is_default is False
    assert second.is_default is True


def test_duplicate_pair_raises(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    with pytest.raises(subs.DuplicateSubstitutionError):
        subs.create_substitution(db, _c("Bulgarian Feta", "Regular Feta"))


def test_self_substitution_rejected(db):
    with pytest.raises(subs.InvalidSubstitutionError):
        subs.create_substitution(db, _c("feta", "feta"))


def test_update_can_reassign_default_via_flag(db):
    first = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    second = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))

    subs.update_substitution(db, second.id, IngredientSubstitutionUpdate(is_default=True))

    db.refresh(first)
    db.refresh(second)
    assert (first.is_default, second.is_default) == (False, True)


def test_update_can_clear_default_leaving_group_with_none(db):
    row = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    subs.update_substitution(db, row.id, IngredientSubstitutionUpdate(is_default=False))
    db.refresh(row)
    assert row.is_default is False
    assert subs.get_default_substitution_map(db) == {}


def test_update_substitute_name_collision_raises(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    other = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))
    with pytest.raises(subs.DuplicateSubstitutionError):
        subs.update_substitution(
            db, other.id, IngredientSubstitutionUpdate(substitute_name="regular feta")
        )


def test_delete_default_does_not_auto_promote(db):
    default = subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    sibling = subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))

    subs.delete_substitution(db, default.id)

    db.refresh(sibling)
    assert sibling.is_default is False
    assert subs.get_default_substitution_map(db) == {}


def test_get_substitution_missing_raises(db):
    with pytest.raises(subs.SubstitutionNotFoundError):
        subs.get_substitution(db, 999)


def test_list_ordered_original_then_default_first(db):
    subs.create_substitution(db, _c("apple", "pear"))
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    subs.create_substitution(db, _c("bulgarian feta", "goat cheese", is_default=True))

    rows, total = subs.list_substitutions(db)
    assert total == 3
    assert [(r.original_name, r.is_default) for r in rows] == [
        ("apple", True),
        ("bulgarian feta", True),  # goat cheese — the default — first in its group
        ("bulgarian feta", False),
    ]


def test_get_default_substitution_map(db):
    subs.create_substitution(db, _c("bulgarian feta", "regular feta"))
    subs.create_substitution(db, _c("banana shallot", "eschalot"))
    subs.create_substitution(db, _c("bulgarian feta", "goat cheese"))  # non-default

    assert subs.get_default_substitution_map(db) == {
        "bulgarian feta": "regular feta",
        "banana shallot": "eschalot",
    }

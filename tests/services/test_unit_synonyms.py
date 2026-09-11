"""Unit tests for app/services/unit_synonyms.py — unit-spelling canonicalisation (2026-09-12,
see CLAUDE.md > Ingredient Unit Handling > Layer A).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.unit_synonyms import UnitSynonymCreate, UnitSynonymUpdate
from app.services import unit_synonyms as us


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


def _c(alias, canonical):
    return UnitSynonymCreate(alias_unit=alias, canonical_unit=canonical)


# --- strip_plural() — the tableless generic heuristic ---------------------------------


def test_strip_plural_common_discrete_units():
    assert us.strip_plural("cloves") == "clove"
    assert us.strip_plural("bunches") == "bunch"
    assert us.strip_plural("sprigs") == "sprig"
    assert us.strip_plural("cans") == "can"
    assert us.strip_plural("boxes") == "box"


def test_strip_plural_leaves_already_singular_alone():
    assert us.strip_plural("clove") == "clove"
    assert us.strip_plural("glass") == "glass"  # ends in "ss" -- not stripped


def test_strip_plural_leaves_short_words_alone():
    # length guard -- "kgs"/"mls" are 3 chars, deliberately not auto-stripped (over-stripping
    # a short word is a worse failure mode than missing one) -- these need an explicit
    # unit_synonyms row instead, see app/seed_data.py > UNIT_SYNONYM_SEEDS.
    assert us.strip_plural("kgs") == "kgs"
    assert us.strip_plural("mls") == "mls"


def test_strip_plural_lowercases():
    assert us.strip_plural("  Cloves ") == "clove"


# --- resolve_unit() --------------------------------------------------------------------


def test_resolve_unit_none_passes_through():
    assert us.resolve_unit(None, {}) == None  # noqa: E711


def test_resolve_unit_strips_plural_before_map_lookup():
    assert us.resolve_unit("cloves", {}) == "clove"


def test_resolve_unit_applies_synonym_after_stripping():
    smap = {"gram": "g"}
    assert us.resolve_unit("gram", smap) == "g"
    assert us.resolve_unit("grams", smap) == "g"  # strips to "gram" first, then maps


def test_resolve_unit_falls_through_when_no_synonym():
    assert us.resolve_unit("tbsp", {}) == "tbsp"


# --- create / list / update / delete ----------------------------------------------------


def test_create_normalises_both_sides(db):
    # canonical_unit is normalised the same way as alias_unit (lowercase, plural-stripped) --
    # consistent with every other normalised field in the app, and harmless for display
    # since consolidation.py's volume branch hardcodes "L"/"ml" regardless of input casing.
    row = us.create_synonym(db, _c("  Grams ", "G"))
    assert (row.alias_unit, row.canonical_unit) == ("gram", "g")


def test_create_rejects_self_synonym(db):
    with pytest.raises(us.InvalidUnitSynonymError):
        us.create_synonym(db, _c("tbsp", "tbsp"))


def test_create_duplicate_alias_raises_409_equivalent(db):
    us.create_synonym(db, _c("gram", "g"))
    with pytest.raises(us.DuplicateUnitSynonymError):
        us.create_synonym(db, _c("gram", "kg"))


def test_list_orders_by_canonical_then_alias(db):
    us.create_synonym(db, _c("tbs", "tbsp"))
    us.create_synonym(db, _c("gram", "g"))
    us.create_synonym(db, _c("tablespoon", "tbsp"))
    rows, total = us.list_synonyms(db)
    assert total == 3
    assert [r.alias_unit for r in rows] == ["gram", "tablespoon", "tbs"]


def test_update_repoints_canonical(db):
    row = us.create_synonym(db, _c("litre", "L"))
    us.update_synonym(db, row.id, UnitSynonymUpdate(canonical_unit="liter"))
    assert row.canonical_unit == "liter"


def test_update_rejects_self_synonym(db):
    row = us.create_synonym(db, _c("litre", "L"))
    with pytest.raises(us.InvalidUnitSynonymError):
        us.update_synonym(db, row.id, UnitSynonymUpdate(canonical_unit="litre"))


def test_update_not_found(db):
    with pytest.raises(us.UnitSynonymNotFoundError):
        us.update_synonym(db, 999, UnitSynonymUpdate(canonical_unit="g"))


def test_delete_only_removes_that_row(db):
    a = us.create_synonym(db, _c("gram", "g"))
    b = us.create_synonym(db, _c("litre", "L"))
    us.delete_synonym(db, a.id)
    remaining, total = us.list_synonyms(db)
    assert total == 1
    assert remaining[0].id == b.id


def test_synonym_map_is_a_flat_dict(db):
    us.create_synonym(db, _c("gram", "g"))
    us.create_synonym(db, _c("litre", "L"))
    assert us.synonym_map(db) == {"gram": "g", "litre": "l"}  # canonical side lowercased too


def test_synonym_map_empty_when_no_rows(db):
    assert us.synonym_map(db) == {}

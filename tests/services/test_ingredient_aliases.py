"""Unit tests for app/services/ingredient_aliases.py — the "same shopping item" grouping
(2026-09-10, see CLAUDE.md > Ingredient Aliases). No DB fixtures shared with substitutions —
this is a deliberately separate concept (see the module docstring).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.ingredient_aliases import IngredientAliasCreate, IngredientAliasUpdate
from app.services import ingredient_aliases as ia


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
    return IngredientAliasCreate(alias_name=alias, canonical_name=canonical)


# --- create ------------------------------------------------------------------------


def test_create_normalises_both_names(db):
    row = ia.create_alias(db, _c("  Canola  Oil ", " Vegetable OIL"))
    assert row.alias_name == "canola oil"
    assert row.canonical_name == "vegetable oil"


def test_create_rejects_self_alias(db):
    with pytest.raises(ia.InvalidIngredientAliasError):
        ia.create_alias(db, _c("olive oil", "olive oil"))


def test_create_rejects_duplicate_alias_name(db):
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    with pytest.raises(ia.DuplicateIngredientAliasError):
        ia.create_alias(db, _c("canola oil", "cooking oil"))


def test_multiple_aliases_can_share_one_canonical(db):
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    ia.create_alias(db, _c("oil spray", "vegetable oil"))
    rows, total = ia.list_aliases(db)
    assert total == 2
    assert {r.alias_name for r in rows} == {"canola oil", "oil spray"}
    assert all(r.canonical_name == "vegetable oil" for r in rows)


# --- chain flattening --------------------------------------------------------------


def test_create_flattens_a_chain_through_an_existing_alias(db):
    # "canola oil" is already an alias for "vegetable oil"; aliasing "spray oil" to
    # "canola oil" must store "spray oil" -> "vegetable oil", not a 2-hop chain.
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    row = ia.create_alias(db, _c("spray oil", "canola oil"))
    assert row.canonical_name == "vegetable oil"


def test_create_flattening_can_reveal_a_self_alias(db):
    # "canola oil" -> "vegetable oil" exists. Trying to add "vegetable oil" -> "canola oil"
    # flattens to "vegetable oil" -> "vegetable oil", which is a self-alias.
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    with pytest.raises(ia.InvalidIngredientAliasError):
        ia.create_alias(db, _c("vegetable oil", "canola oil"))


def test_create_repoints_existing_rows_that_pointed_at_the_new_alias_name(db):
    # "canola oil" -> "vegetable oil" exists. Now "vegetable oil" itself becomes an alias
    # for "neutral oil" -- the existing row must be re-pointed to stay flat, not left
    # pointing at something that's now itself an alias.
    canola = ia.create_alias(db, _c("canola oil", "vegetable oil"))
    ia.create_alias(db, _c("vegetable oil", "neutral oil"))
    db.refresh(canola)
    assert canola.canonical_name == "neutral oil"


def test_update_flattens_the_new_canonical_too(db):
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    row = ia.create_alias(db, _c("spray oil", "olive oil"))
    updated = ia.update_alias(db, row.id, IngredientAliasUpdate(canonical_name="canola oil"))
    assert updated.canonical_name == "vegetable oil"  # flattened, not left at "canola oil"


def test_update_rejects_a_self_alias(db):
    row = ia.create_alias(db, _c("canola oil", "vegetable oil"))
    with pytest.raises(ia.InvalidIngredientAliasError):
        ia.update_alias(db, row.id, IngredientAliasUpdate(canonical_name="canola oil"))


# --- alias_map / resolve helper -----------------------------------------------------


def test_alias_map_is_a_flat_dict_of_resolutions(db):
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    ia.create_alias(db, _c("oil spray", "vegetable oil"))
    m = ia.alias_map(db)
    assert set(m) == {"canola oil", "oil spray"}
    assert m["canola oil"].canonical_name == "vegetable oil"
    assert m["canola oil"].has_pair is False


def test_alias_map_carries_the_equivalence_pair(db):
    create = IngredientAliasCreate(
        alias_name="lemon juice", canonical_name="lemon",
        alias_qty=2, alias_unit="tbsp", canonical_qty=1, canonical_unit=None,
    )
    ia.create_alias(db, create)
    res = ia.alias_map(db)["lemon juice"]
    assert res.has_pair is True
    assert res.canonical_name == "lemon"
    assert res.alias_qty == 2 and res.alias_unit == "tbsp"
    assert res.canonical_qty == 1 and res.canonical_unit is None


def test_alias_map_empty_when_no_rows(db):
    assert ia.alias_map(db) == {}


# --- get / delete --------------------------------------------------------------------


def test_get_missing_raises(db):
    with pytest.raises(ia.IngredientAliasNotFoundError):
        ia.get_alias(db, 999)


# --- equivalence pair (2026-09-10, lemon/lime juice -> whole fruit) ------------------


def _cp(alias, canonical, aq, au, cq, cu):
    return IngredientAliasCreate(
        alias_name=alias, canonical_name=canonical,
        alias_qty=aq, alias_unit=au, canonical_qty=cq, canonical_unit=cu,
    )


def test_create_with_equivalence_pair_stores_normalised_units(db):
    row = ia.create_alias(db, _cp("lemon juice", "lemon", 2, "  TBSP ", 1, None))
    assert (row.alias_qty, row.alias_unit) == (2, "tbsp")
    assert (row.canonical_qty, row.canonical_unit) == (1, None)


def test_canonical_unit_may_be_blank_for_a_bare_count_target(db):
    # "1 lemon" has no unit -- same as recipe_ingredients.unit being NULL for unitless
    # produce. This is the whole reason ingredient_aliases has its own validator instead of
    # reusing schemas.substitutions.validate_equivalence_pair verbatim.
    row = ia.create_alias(db, _cp("lemon juice", "lemon", 3, "tbsp", 1, ""))
    assert row.canonical_unit is None


def test_create_rejects_half_a_pair(db):
    with pytest.raises(ValidationError):
        _cp("lemon juice", "lemon", 2, "tbsp", None, None)


def test_create_rejects_zero_alias_qty(db):
    with pytest.raises(ValidationError):
        _cp("lemon juice", "lemon", 0, "tbsp", 1, None)


def test_update_can_set_and_clear_the_pair(db):
    row = ia.create_alias(db, _c("lemon juice", "lemon"))
    assert row.alias_qty is None

    ia.update_alias(
        db, row.id,
        IngredientAliasUpdate(alias_qty=2, alias_unit="tbsp", canonical_qty=1, canonical_unit=None),
    )
    assert (row.alias_qty, row.alias_unit) == (2, "tbsp")
    assert row.canonical_qty == 1

    ia.update_alias(
        db, row.id,
        IngredientAliasUpdate(alias_qty=None, alias_unit=None, canonical_qty=None, canonical_unit=None),
    )
    assert row.alias_qty is None and row.canonical_qty is None


def test_note_is_stored_and_trimmed(db):
    create = IngredientAliasCreate(
        alias_name="lemon juice", canonical_name="lemon", note="  roughly 3 tbsp per lemon  "
    )
    row = ia.create_alias(db, create)
    assert row.note == "roughly 3 tbsp per lemon"


def test_delete_only_removes_that_row(db):
    a = ia.create_alias(db, _c("canola oil", "vegetable oil"))
    b = ia.create_alias(db, _c("oil spray", "vegetable oil"))
    ia.delete_alias(db, a.id)
    remaining, total = ia.list_aliases(db)
    assert total == 1 and remaining[0].id == b.id

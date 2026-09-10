"""Unit tests for app/services/ingredient_aliases.py — the "same shopping item" grouping
(2026-09-10, see CLAUDE.md > Ingredient Aliases). No DB fixtures shared with substitutions —
this is a deliberately separate concept (see the module docstring).
"""

from __future__ import annotations

import pytest
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


def test_alias_map_is_a_flat_dict(db):
    ia.create_alias(db, _c("canola oil", "vegetable oil"))
    ia.create_alias(db, _c("oil spray", "vegetable oil"))
    assert ia.alias_map(db) == {"canola oil": "vegetable oil", "oil spray": "vegetable oil"}


def test_alias_map_empty_when_no_rows(db):
    assert ia.alias_map(db) == {}


# --- get / delete --------------------------------------------------------------------


def test_get_missing_raises(db):
    with pytest.raises(ia.IngredientAliasNotFoundError):
        ia.get_alias(db, 999)


def test_delete_only_removes_that_row(db):
    a = ia.create_alias(db, _c("canola oil", "vegetable oil"))
    b = ia.create_alias(db, _c("oil spray", "vegetable oil"))
    ia.delete_alias(db, a.id)
    remaining, total = ia.list_aliases(db)
    assert total == 1 and remaining[0].id == b.id

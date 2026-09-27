"""Unit tests for app/seed_data.py's seed_reference_data() — focused on the
2026-09-27 household-preference alias additions (ingredient-name-matching plan, chunk F0).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.catalog import IngredientAlias, ProductUnit
from app.seed_data import seed_reference_data


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
        engine.dispose()


def test_seed_creates_the_four_preference_aliases(db):
    seed_reference_data(db)
    rows = {r.alias_name: r.canonical_name for r in db.query(IngredientAlias).all()}

    assert rows["heavy cream"] == "thickened cream"
    assert rows["broth"] == "stock"
    assert rows["plain yogurt"] == "greek yoghurt"
    assert rows["plain yoghurt"] == "greek yoghurt"


def test_seed_is_idempotent_for_the_preference_aliases(db):
    seed_reference_data(db)
    seed_reference_data(db)
    count = (
        db.query(IngredientAlias)
        .filter(IngredientAlias.alias_name.in_(["heavy cream", "broth", "plain yogurt", "plain yoghurt"]))
        .count()
    )
    assert count == 4


def test_seed_never_resurrects_a_deleted_system_alias(db):
    """Fix 2, F2.4 — the 3 legacy system alias groups (migration 62a354151f0d) are
    deliberately NOT in INGREDIENT_ALIAS_SEEDS, precisely so a household deleting one of them
    via Settings sees it stay gone across every future restart, unlike the user-preference
    rows above which re-seed if missing."""
    row = IngredientAlias(alias_name="table salt", canonical_name="salt", source="system")
    db.add(row)
    db.commit()
    db.delete(row)
    db.commit()

    seed_reference_data(db)

    assert db.query(IngredientAlias).filter(IngredientAlias.alias_name == "table salt").first() is None


def test_seed_creates_the_fix5_accepted_aliases_already_normalised(db):
    """Fix 5, F5.2 — accepted from a real suggest_ingredient_groupings() audit. Every string
    here must already be in normalised form (seed_reference_data()'s loop inserts raw, with no
    normaliser applied on the way in) — this test locks in the exact stored strings, not just
    that a row exists, since a subtly wrong literal would silently never match anything."""
    seed_reference_data(db)
    rows = {r.alias_name: r.canonical_name for r in db.query(IngredientAlias).all()}

    assert rows["dried chilli flake"] == "chilli flake"
    assert rows["whole egg mayonnaise"] == "mayonnaise"
    assert rows["milk"] == "full cream milk"
    assert rows["whole milk"] == "full cream milk"
    assert rows["full fat coconut milk"] == "coconut milk"
    assert rows["sugar"] == "white sugar"
    assert rows["boneless skinless chicken breast"] == "chicken breast"
    assert rows["cumin"] == "ground cumin"
    assert rows["turmeric"] == "ground turmeric"
    assert rows["diced tomato"] == "canned tomato"
    assert rows["crushed tomato"] == "canned tomato"
    # Explicitly rejected by the maintainer — must never be seeded.
    assert rows.get("flour") != "plain flour"
    assert "garlic clove" not in rows and "garlic cloves" not in rows
    assert "coriander" not in rows and "parsley" not in rows


def test_seed_fix5_alias_strings_all_match_the_real_normaliser(db):
    """Confirms every Fix 5 alias string is genuinely already normalised, not just internally
    consistent with itself — regression guard for the exact bug this chunk caught by hand
    (seed_reference_data() never normalises on insert, unlike create_alias())."""
    from app.services import text_normalize

    seed_reference_data(db)
    rows = db.query(IngredientAlias).filter(IngredientAlias.source == "user").all()
    for row in rows:
        assert text_normalize.normalise_ingredient_name(row.alias_name) == row.alias_name, (
            f"{row.alias_name!r} is not already in normalised form"
        )
        assert text_normalize.normalise_ingredient_name(row.canonical_name) == row.canonical_name, (
            f"{row.canonical_name!r} is not already in normalised form"
        )


def test_seed_product_units_repointed_to_fix5_canonical_names(db):
    seed_reference_data(db)
    names = {r.ingredient_name for r in db.query(ProductUnit).all()}
    assert "full cream milk" in names
    assert "canned tomato" in names
    assert "milk" not in names
    assert "diced tomato" not in names

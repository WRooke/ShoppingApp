"""Unit tests for app/seed_data.py's seed_reference_data() — focused on the
2026-09-27 household-preference alias additions (ingredient-name-matching plan, chunk F0).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.catalog import IngredientAlias
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

"""Unit tests for app/services/product_sections.py — no DB network, no Claude involved."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.store import ProductSection
from app.services.product_sections import tag_suggested_sections


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


def test_tag_suggested_sections_writes_new_rows(db):
    added = tag_suggested_sections(db, {"beef mince": "meat & seafood", "onion": "produce"})

    assert added == 2
    rows = {row.ingredient_name: row.section_name for row in db.query(ProductSection).all()}
    assert rows == {"beef mince": "meat & seafood", "onion": "produce"}
    assert all(row.source == "ai_suggested" for row in db.query(ProductSection).all())


def test_tag_suggested_sections_empty_dict_is_a_noop(db):
    added = tag_suggested_sections(db, {})
    assert added == 0
    assert db.query(ProductSection).count() == 0


def test_tag_suggested_sections_never_overwrites_existing_row(db):
    db.add(ProductSection(ingredient_name="onion", section_name="pantry", source="user_corrected"))
    db.commit()

    added = tag_suggested_sections(db, {"onion": "produce", "garlic": "produce"})

    assert added == 1  # only garlic was new
    onion_row = db.query(ProductSection).filter_by(ingredient_name="onion").one()
    assert onion_row.section_name == "pantry"
    assert onion_row.source == "user_corrected"
    assert db.query(ProductSection).filter_by(ingredient_name="garlic").one().source == "ai_suggested"

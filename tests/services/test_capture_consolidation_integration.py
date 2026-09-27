"""Fake-mode integration test: does a real `ai_extraction.capture_recipe()` call flow correctly
through recipe save -> session -> consolidate under Fix 1's shared normaliser
(app/services/text_normalize.py)? Promoted from an ad-hoc verification script run by hand during
the ingredient-name-matching plan's Fix 1 go/no-go — see that plan's Testing & Verification
section. This is what caught the original "tofus" bug (an early `inflect`-adoption regression,
since fixed) before it reached any real household data.

Unlike the rest of the Fix 1 unit tests (which call `text_normalize`/`consolidation` directly),
this drives the *actual* capture -> recipe -> session -> consolidate pipeline end-to-end, so it
also catches any integration-level break the isolated unit tests wouldn't (serialisation,
service wiring, etc.).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.seed_data import seed_reference_data
from app.services import ai_extraction, recipes as recipes_service
from app.services import session_consolidation, sessions as sessions_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    seed_reference_data(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def fake_mode(monkeypatch):
    monkeypatch.setattr("app.services.ai_extraction.settings.ai_extraction_fake_mode", True)


def test_real_capture_merges_with_a_manually_typed_plural_variant(db, fake_mode):
    # A real capture_recipe() call (fake mode — no network, no spend) rather than hand-built
    # ExtractedIngredient objects, so this exercises the actual capture->schema->ORM path a real
    # AI extraction would, not just a Python-level construction of the same shape.
    result = ai_extraction.capture_recipe(
        db, call_type="test", text="a fake recipe for this integration test"
    )
    assert result.ingredients, "fake mode must still return at least one ingredient"

    captured = recipes_service.create_recipe(
        db,
        RecipeCreate(
            name="Captured — " + (result.title or "fixture"),
            source_type="url",
            source_url="https://example.com/fake-capture-integration-test",
            base_servings=result.servings or 4,
            ingredients=[
                RecipeIngredientCreate(
                    name=i.name, quantity=i.quantity, unit=i.unit, preparation=i.preparation,
                    suggested_section=i.suggested_section,
                )
                for i in result.ingredients
            ],
        ),
    )

    # A manually-entered recipe using a plural variant of whichever ingredient the fixture
    # actually came back with (fixture selection is a hash of the input text, not
    # content-matched — build the test around whatever was actually captured, not a specific
    # fixture's contents).
    target = result.ingredients[0].name
    plural_variant = target + "s"
    fixture_qty = result.ingredients[0].quantity
    manual = recipes_service.create_recipe(
        db,
        RecipeCreate(
            name=f"Manual — extra {plural_variant}",
            source_type="manual",
            base_servings=4,
            ingredients=[RecipeIngredientCreate(name=plural_variant, quantity=100, unit="g")],
        ),
    )

    session = sessions_service.create_session(db, PlanningSessionCreate())
    sessions_service.add_session_recipe(
        db, session.id, SessionRecipeCreate(recipe_id=captured.id, scaled_servings=4)
    )
    sessions_service.add_session_recipe(
        db, session.id, SessionRecipeCreate(recipe_id=manual.id, scaled_servings=4)
    )

    items = session_consolidation.consolidate_session(db, session.id)
    by_name = {i.ingredient_name: i for i in items}

    assert target in by_name, f"captured {target!r} + manual {plural_variant!r} must merge"
    assert plural_variant not in by_name, "the raw plural must not survive as its own line"
    assert by_name[target].total_quantity == fixture_qty + 100

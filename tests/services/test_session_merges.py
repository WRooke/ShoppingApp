"""Unit tests for app/services/session_merges.py — the session-scoped counterpart to
ingredient_aliases (Fix 3, F3.1). No DB fixtures shared with ingredient_aliases — this is a
deliberately separate, ephemeral concept (see the module docstring).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.planning import SessionIngredientMerge
from app.schemas.sessions import PlanningSessionCreate
from app.services import session_merges as sm
from app.services import sessions as sessions_service


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


def _session(db):
    return sessions_service.create_session(db, PlanningSessionCreate())


def test_add_and_read_back_name_only_merge(db):
    s = _session(db)
    sm.add_session_merge(db, s.id, "carrot", "carrots")
    result = sm.session_merge_map(db, s.id)
    assert result["carrot"].canonical_name == "carrots"
    assert result["carrot"].has_pair is False


def test_add_merge_with_pair(db):
    s = _session(db)
    sm.add_session_merge(
        db, s.id, "lemon juice", "lemon",
        alias_qty=3, alias_unit="tbsp", canonical_qty=1, canonical_unit=None,
    )
    result = sm.session_merge_map(db, s.id)
    assert result["lemon juice"].canonical_name == "lemon"
    assert result["lemon juice"].has_pair is True
    assert result["lemon juice"].alias_qty == 3 and result["lemon juice"].alias_unit == "tbsp"


def test_adding_a_second_merge_for_the_same_member_re_points_not_duplicates(db):
    s = _session(db)
    sm.add_session_merge(db, s.id, "carrot", "carrots")
    sm.add_session_merge(db, s.id, "carrot", "orange carrot")  # re-point
    result = sm.session_merge_map(db, s.id)
    assert result["carrot"].canonical_name == "orange carrot"
    assert (
        db.query(SessionIngredientMerge)
        .filter(SessionIngredientMerge.session_id == s.id, SessionIngredientMerge.member_name == "carrot")
        .count()
        == 1
    )


def test_session_merge_map_only_returns_this_sessions_own_rows(db):
    s1 = _session(db)
    s2 = _session(db)
    sm.add_session_merge(db, s1.id, "carrot", "carrots")
    assert sm.session_merge_map(db, s2.id) == {}


def test_clear_session_merges_removes_only_that_sessions_rows(db):
    s1 = _session(db)
    s2 = _session(db)
    sm.add_session_merge(db, s1.id, "carrot", "carrots")
    sm.add_session_merge(db, s2.id, "onion", "onions")
    sm.clear_session_merges(db, s1.id)
    assert sm.session_merge_map(db, s1.id) == {}
    assert "onion" in sm.session_merge_map(db, s2.id)


def test_deleting_a_session_cascades_to_its_merges(db):
    s = _session(db)
    sm.add_session_merge(db, s.id, "carrot", "carrots")
    session_row = sessions_service.get_session(db, s.id)
    db.delete(session_row)
    db.commit()
    assert db.query(SessionIngredientMerge).count() == 0

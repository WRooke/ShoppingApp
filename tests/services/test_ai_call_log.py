"""Unit tests for app/services/ai_call_log.py (Phase 3.9 M5). No cost math — Gemini's free
tier has no per-call dollar cost."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.diagnostics import AiCallLog
from app.services import ai_call_log


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


def test_task_for_maps_call_types():
    assert ai_call_log.task_for("recipe_url") == "extract"
    assert ai_call_log.task_for("recipe_photo") == "extract"
    assert ai_call_log.task_for("flag_substitutions") == "flag_substitutions"
    assert ai_call_log.task_for("suggest_sections") == "suggest_sections"


def test_log_ai_call_success(db):
    row = ai_call_log.log_ai_call(
        db, call_type="recipe_url", model="gemini-2.5-flash", outcome="success",
        input_tokens=1200, output_tokens=300, context_id="7",
    )
    assert row.task == "extract" and row.outcome == "success"
    assert row.input_tokens == 1200 and row.context_id == "7"


def test_log_ai_call_quota_and_error(db):
    ai_call_log.log_ai_call(db, call_type="recipe_url", model="gemini-2.5-flash", outcome="quota")
    ai_call_log.log_ai_call(
        db, call_type="suggest_sections", model="gemini-2.5-flash-lite", outcome="error",
        error_detail="boom" * 1000,
    )
    rows = ai_call_log.recent_calls(db, limit=10)
    assert {r.outcome for r in rows} == {"quota", "error"}
    assert len(next(r for r in rows if r.outcome == "error").error_detail) <= 2000  # truncated


def test_today_counts_by_model_ignores_yesterday(db):
    ai_call_log.log_ai_call(db, call_type="recipe_url", model="gemini-2.5-flash", outcome="success")
    ai_call_log.log_ai_call(db, call_type="recipe_url", model="gemini-2.5-flash", outcome="quota")
    ai_call_log.log_ai_call(db, call_type="recipe_photo", model="gemini-2.5-flash-lite", outcome="success")
    # backdate one row to yesterday
    old = db.query(AiCallLog).first()
    old.timestamp = datetime.now(timezone.utc) - timedelta(days=1, hours=2)
    db.commit()

    counts = ai_call_log.today_counts_by_model(db)
    assert counts.get("gemini-2.5-flash", 0) == 1  # one of the two flash rows was backdated
    assert counts.get("gemini-2.5-flash-lite", 0) == 1


def test_last_success_at(db):
    assert ai_call_log.last_success_at(db) is None
    ai_call_log.log_ai_call(db, call_type="recipe_url", model="gemini-2.5-flash", outcome="quota")
    assert ai_call_log.last_success_at(db) is None
    ai_call_log.log_ai_call(db, call_type="recipe_url", model="gemini-2.5-flash", outcome="success")
    assert ai_call_log.last_success_at(db) is not None


def test_recent_calls_newest_first(db):
    for i in range(5):
        ai_call_log.log_ai_call(
            db, call_type="recipe_url", model="gemini-2.5-flash", outcome="success", context_id=str(i)
        )
    rows = ai_call_log.recent_calls(db, limit=3)
    assert [r.context_id for r in rows] == ["4", "3", "2"]

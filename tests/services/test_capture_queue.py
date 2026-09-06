"""Unit tests for app/services/capture_queue.py (Phase 3.9 M3) — the Gemini-429 retry
queue. No network: the AI calls it drives are mocked / fake-mode."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.queue import CaptureQueueItem
from app.services import ai_extraction, capture_queue


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


@pytest.fixture()
def fake_mode(monkeypatch):
    monkeypatch.setattr("app.services.ai_extraction.settings.ai_extraction_fake_mode", True)


def test_enqueue_and_due_items(db):
    capture_queue.enqueue(db, task="extract_url", payload={"url": "https://x/a", "source_type": "url"})
    capture_queue.enqueue(db, task="suggest_sections", payload={"names": ["onion"]}, recipe_id=1)

    items = capture_queue.due_items(db)
    assert [i.task for i in items] == ["extract_url", "suggest_sections"]
    assert json.loads(items[0].payload_json)["url"] == "https://x/a"
    assert items[1].recipe_id == 1
    assert items[0].attempt_count == 0


def test_record_attempt_and_remove(db):
    item = capture_queue.enqueue(db, task="extract_url", payload={"url": "u", "source_type": "url"})
    capture_queue.record_attempt(db, item, error="still over quota")
    db.refresh(item)
    assert item.attempt_count == 1 and item.last_error == "still over quota"
    assert item.last_attempt_at is not None

    capture_queue.remove(db, item)
    assert db.query(CaptureQueueItem).count() == 0


def test_run_once_extract_url_success_creates_recipe_and_removes_row(db, fake_mode):
    capture_queue.enqueue(
        db,
        task="extract_url",
        payload={"url": "https://example.com/tacos", "source_type": "url", "fallback_name": "Queued Tacos"},
    )
    # capture_url.fetch_and_extract does a real httpx.get before the (fake-mode) AI call —
    # mock the fetch, let fake mode handle extraction.
    from unittest.mock import MagicMock

    html_resp = MagicMock()
    html_resp.text = "<article>500g beef mince, 1 onion</article>"
    html_resp.content = b"x"
    html_resp.raise_for_status.return_value = None

    with patch("app.services.capture_url.httpx.get", return_value=html_resp):
        summary = capture_queue.run_once(db)

    assert summary == {"processed": 1, "succeeded": 1, "still_queued": 0, "skipped": 0}
    assert db.query(CaptureQueueItem).count() == 0
    from app.models.recipes import Recipe

    recipe = db.query(Recipe).one()
    assert recipe.name == "Queued Tacos"
    assert recipe.source_url == "https://example.com/tacos"
    assert len(recipe.ingredients) > 0


def test_run_once_still_quota_keeps_row_and_records_attempt(db):
    item = capture_queue.enqueue(
        db, task="extract_url", payload={"url": "https://x/a", "source_type": "url"}
    )
    from unittest.mock import MagicMock

    html_resp = MagicMock()
    html_resp.text = "<article>stuff</article>"
    html_resp.content = b"x"
    html_resp.raise_for_status.return_value = None

    with patch("app.services.capture_url.httpx.get", return_value=html_resp), patch(
        "app.services.ai_extraction.capture_recipe",
        side_effect=ai_extraction.AiQuotaExhaustedError("still over quota"),
    ):
        summary = capture_queue.run_once(db)

    assert summary["still_queued"] == 1 and summary["succeeded"] == 0
    db.refresh(item)
    assert item.attempt_count == 1 and item.last_error == "still over quota"
    assert db.query(CaptureQueueItem).count() == 1


def test_run_once_skips_enrichment_tasks_until_m4(db):
    capture_queue.enqueue(db, task="suggest_sections", payload={"names": ["onion"]}, recipe_id=1)
    summary = capture_queue.run_once(db)
    assert summary == {"processed": 1, "succeeded": 0, "still_queued": 0, "skipped": 1}
    assert db.query(CaptureQueueItem).count() == 1  # left alone

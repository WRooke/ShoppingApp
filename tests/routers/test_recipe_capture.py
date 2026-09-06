"""Smoke tests for /api/v1/recipes/capture/* — happy path + one error path per endpoint,
per CLAUDE.md > Code Architecture & Maintainability.

Fake mode (CLAUDE.md > Security > §0c) is forced on for every test here so these never depend
on the developer's local .env state and never make a real Gemini call — the URL endpoint's
own network fetch is separately mocked (httpx.get), since fake mode only covers the Gemini
call, not capture_url's own HTTP fetch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models.diagnostics import AiCallLog
from app.models.store import ProductSection
from app.services.ai_extraction import AiQuotaExhaustedError


@pytest.fixture(autouse=True)
def fake_mode(monkeypatch):
    monkeypatch.setattr(settings, "ai_extraction_fake_mode", True)


def _mock_html_response(html: str):
    response = MagicMock()
    response.text = html
    response.content = html.encode("utf-8")
    response.raise_for_status.return_value = None
    return response


# --- /capture/url ------------------------------------------------------------


def test_capture_from_url_happy_path(client):
    html = "<html><body><article>500g beef mince, 1 onion diced</article></body></html>"
    with patch("app.services.capture_url.httpx.get", return_value=_mock_html_response(html)):
        resp = client.post("/api/v1/recipes/capture/url", json={"url": "https://example.com/tacos"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["source_type"] == "url"
    assert body["data"]["source_url"] == "https://example.com/tacos"
    assert len(body["data"]["ingredients"]) > 0
    # Fake mode never writes usage rows — nothing was actually billed.
    db = SessionLocal()
    try:
        assert db.query(AiCallLog).count() == 0
    finally:
        db.close()


def test_capture_from_url_rejects_missing_url(client):
    resp = client.post("/api/v1/recipes/capture/url", json={})

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_capture_from_url_returns_fetch_failed_on_unreachable_url(client):
    import httpx

    with patch("app.services.capture_url.httpx.get", side_effect=httpx.ConnectError("refused")):
        resp = client.post("/api/v1/recipes/capture/url", json={"url": "https://example.com/down"})

    assert resp.status_code == 502
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "RECIPE_FETCH_FAILED"


# --- /capture/photo ------------------------------------------------------


def test_capture_from_photo_happy_path(client):
    resp = client.post(
        "/api/v1/recipes/capture/photo",
        files={"image": ("recipe.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["source_type"] == "photo"
    assert body["data"]["source_image_path"].endswith(".jpg")
    assert len(body["data"]["ingredients"]) > 0


def test_capture_from_photo_rejects_unsupported_type(client):
    resp = client.post(
        "/api/v1/recipes/capture/photo",
        files={"image": ("recipe.gif", b"whatever", "image/gif")},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_IMAGE"


# --- /capture/confirm ------------------------------------------------------


def test_confirm_capture_saves_recipe_and_product_sections(client):
    payload = {
        "name": "ZZ-Capture-Confirm-Test",
        "source_type": "url",
        "source_url": "https://example.com/tacos",
        "base_servings": 4,
        "cuisine": "mexican",
        "protein": "beef mince",
        "ingredients": [
            {
                "name": "ZZ-Test-Beef-Mince",
                "quantity": 500,
                "unit": "g",
                "suggested_section": "meat & seafood",
            },
        ],
    }
    resp = client.post("/api/v1/recipes/capture/confirm", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "ZZ-Capture-Confirm-Test"
    assert body["data"]["ingredients"][0]["name"] == "zz-test-beef-mince"

    db = SessionLocal()
    try:
        section = db.query(ProductSection).filter_by(ingredient_name="zz-test-beef-mince").one()
        assert section.section_name == "meat & seafood"
        assert section.source == "ai_suggested"
    finally:
        db.query(ProductSection).filter_by(ingredient_name="zz-test-beef-mince").delete()
        db.commit()
        db.close()


def test_confirm_capture_rejects_missing_name(client):
    resp = client.post(
        "/api/v1/recipes/capture/confirm",
        json={"source_type": "manual", "ingredients": []},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


# --- Gemini-429 retry queue (Phase 3.9 M3) --------------------------------------


def test_capture_url_over_quota_is_queued(client):
    html = "<html><body><article>500g beef mince</article></body></html>"
    with patch("app.services.capture_url.httpx.get", return_value=_mock_html_response(html)), patch(
        "app.services.ai_extraction.capture_recipe",
        side_effect=AiQuotaExhaustedError("over quota"),
    ):
        resp = client.post("/api/v1/recipes/capture/url", json={"url": "https://example.com/x"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["queued"] is True

    db = SessionLocal()
    try:
        from app.models.queue import CaptureQueueItem

        row = db.query(CaptureQueueItem).filter_by(task="extract_url").order_by(CaptureQueueItem.id.desc()).first()
        assert row is not None
        import json as _json

        assert _json.loads(row.payload_json)["url"] == "https://example.com/x"
    finally:
        db.close()

"""Smoke tests for /api/v1/diagnostics/* — see CLAUDE.md > Code Architecture &
Maintainability. Assertions avoid depending on GEMINI_API_KEY / ANYLIST_* being configured
in .env (varies by machine) and check shape/invariants instead.

**Phase 3.9 M5:** the USD "spend tracker" + its reset button are gone (Gemini free tier).
The AI block now carries a daily quota indicator (`today_by_model`) + a recent-attempt log.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.diagnostics import AiCallLog


def test_status_reports_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_extraction_enabled", False)
    monkeypatch.setattr(settings, "ai_extraction_fake_mode", False)

    resp = client.get("/api/v1/diagnostics/status")
    data = resp.json()["data"]["ai_extraction"]

    assert data["api_enabled"] is False
    assert data["fake_mode"] is False
    assert data["state"] == "grey"
    assert "Disabled" in data["message"]


def test_status_reports_fake_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_extraction_fake_mode", True)

    resp = client.get("/api/v1/diagnostics/status")
    data = resp.json()["data"]["ai_extraction"]

    assert data["fake_mode"] is True
    assert data["state"] == "amber"
    assert "FAKE MODE" in data["message"]


def test_status_reports_ok_envelope_and_component_shapes(client):
    resp = client.get("/api/v1/diagnostics/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    data = body["data"]
    assert set(data.keys()) == {"database", "ai_extraction", "anylist"}
    assert data["database"]["state"] == "green"

    ai = data["ai_extraction"]
    assert isinstance(ai["api_enabled"], bool)
    assert isinstance(ai["fake_mode"], bool)
    assert isinstance(ai["today_by_model"], dict)
    assert isinstance(ai["recent_calls"], list)
    assert "last_success" in ai
    assert ai["dashboard_url"].startswith("https://")

    assert data["anylist"]["state"] in ("grey", "amber")


def test_status_quota_indicator_counts_todays_calls_by_model(client):
    db = SessionLocal()
    ids = []
    try:
        for _ in range(3):
            row = AiCallLog(
                timestamp=datetime.now(timezone.utc),
                task="extract",
                model="gemini-2.5-flash",
                outcome="success",
                input_tokens=100,
                output_tokens=20,
            )
            db.add(row)
            db.commit()
            ids.append(row.id)

        ai = client.get("/api/v1/diagnostics/status").json()["data"]["ai_extraction"]
        assert ai["today_by_model"].get("gemini-2.5-flash", 0) >= 3
        assert any(c["model"] == "gemini-2.5-flash" for c in ai["recent_calls"])
    finally:
        db.query(AiCallLog).filter(AiCallLog.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_logs_returns_entries_and_respects_limit(client):
    # Generate at least one log entry to be sure the ring buffer isn't empty.
    client.get("/api/v1/health")

    resp = client.get("/api/v1/diagnostics/logs?limit=1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["entries"]) <= 1


def test_logs_rejects_invalid_level_with_structured_error(client):
    resp = client.get("/api/v1/diagnostics/logs?level=NOT_A_LEVEL")

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_recent_errors_returns_ok_envelope(client):
    resp = client.get("/api/v1/diagnostics/recent-errors")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"]["entries"], list)
    assert len(body["data"]["entries"]) <= 10

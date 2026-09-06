"""Smoke tests for /api/v1/diagnostics/* — see CLAUDE.md > Code Architecture &
Maintainability (every router gets at least a happy-path + one error-path test once
it has real logic behind it). diagnostics.py has real logic in Phase 1 (log
filtering/pagination, a DB probe, an api_usage aggregate query) even though the
AnyList indicator itself is a stub until Phase 5.

Assertions here deliberately avoid depending on ANTHROPIC_API_KEY / ANYLIST_* actually
being configured in .env — that varies by machine (this dev machine's .env already has
real AnyList credentials from the Phase 1.5 spike) — and check shape/invariants instead.

**2026-09-06:** the hard AU$0.50 spend cap this file used to test has been removed — see
CLAUDE.md > Non-Negotiable Operating Rules and Security §0b. What replaced the
spend-cap-reached test is coverage of the reset-with-confirmation endpoint
(`POST /api/v1/diagnostics/reset-spend`), which is purely a display reset.
"""

from __future__ import annotations

from app.config import settings
from app.database import SessionLocal
from app.models.diagnostics import ApiUsage, ApiUsageReset


def test_status_reports_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_extraction_enabled", False)
    monkeypatch.setattr(settings, "ai_extraction_fake_mode", False)

    resp = client.get("/api/v1/diagnostics/status")
    data = resp.json()["data"]["claude_api"]

    assert data["api_enabled"] is False
    assert data["fake_mode"] is False
    assert data["state"] == "grey"
    assert "Disabled" in data["message"]


def test_status_reports_fake_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_extraction_fake_mode", True)

    resp = client.get("/api/v1/diagnostics/status")
    data = resp.json()["data"]["claude_api"]

    assert data["fake_mode"] is True
    assert data["state"] == "amber"
    assert "FAKE MODE" in data["message"]


def test_status_reports_ok_envelope_and_component_shapes(client):
    resp = client.get("/api/v1/diagnostics/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    data = body["data"]
    assert set(data.keys()) == {"database", "claude_api", "anylist"}

    # The DB is real and reachable in the test client's app lifespan, so this should
    # always be green regardless of what's configured in .env.
    assert data["database"]["state"] == "green"

    # Enable-switch and fake-mode fields (CLAUDE.md > Security > §0c) must always be present.
    assert isinstance(data["claude_api"]["api_enabled"], bool)
    assert isinstance(data["claude_api"]["fake_mode"], bool)

    # Spend/token fields (CLAUDE.md > Security > §0b) are observational only — always present,
    # never a pass/fail gate.
    assert "estimated_spend_usd" in data["claude_api"]
    assert "total_input_tokens" in data["claude_api"]
    assert "total_output_tokens" in data["claude_api"]
    assert "reset_at" in data["claude_api"]

    assert data["anylist"]["state"] in ("grey", "amber")


def test_reset_spend_inserts_marker_and_resets_display_totals(client):
    # Writes directly to the shared test DB (api_usage has no delete endpoint — it's an
    # append-only log per CLAUDE.md > Data Model), so rows are removed again afterwards to
    # avoid leaking spend/reset state into other tests in this session.
    db = SessionLocal()
    usage_row_id = None
    try:
        usage_row = ApiUsage(
            model="claude-haiku-4-5",
            input_tokens=500,
            output_tokens=100,
            cost_usd_cents=1.0,
            call_type="recipe_url",
        )
        db.add(usage_row)
        db.commit()
        usage_row_id = usage_row.id

        before = client.get("/api/v1/diagnostics/status").json()["data"]["claude_api"]
        assert before["total_input_tokens"] >= 500

        resp = client.post("/api/v1/diagnostics/reset-spend")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["reset_at"] is not None

        after = client.get("/api/v1/diagnostics/status").json()["data"]["claude_api"]
        # Display totals are since the reset — the row logged above no longer counts.
        assert after["total_input_tokens"] == 0
        assert after["total_output_tokens"] == 0
        assert after["estimated_spend_usd"] == 0.0
        assert after["reset_at"] is not None

        # The underlying api_usage row is untouched — never deleted by a reset.
        assert db.query(ApiUsage).filter(ApiUsage.id == usage_row_id).count() == 1
    finally:
        if usage_row_id is not None:
            db.query(ApiUsage).filter(ApiUsage.id == usage_row_id).delete()
        db.query(ApiUsageReset).delete()
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

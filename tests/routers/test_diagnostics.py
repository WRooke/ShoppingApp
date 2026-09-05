"""Smoke tests for /api/v1/diagnostics/* — see CLAUDE.md > Code Architecture &
Maintainability (every router gets at least a happy-path + one error-path test once
it has real logic behind it). diagnostics.py has real logic in Phase 1 (log
filtering/pagination, a DB probe, an api_usage aggregate query) even though the
Claude/AnyList indicators themselves are stubs until Phases 3 and 5.

Assertions here deliberately avoid depending on ANTHROPIC_API_KEY / ANYLIST_* actually
being configured in .env — that varies by machine (this dev machine's .env already has
real AnyList credentials from the Phase 1.5 spike) — and check shape/invariants instead.
"""

from __future__ import annotations

from app.database import SessionLocal
from app.models.diagnostics import ApiUsage
from app.services.api_usage import get_spend_cap_usd_cents


def test_status_reports_spend_cap_reached_as_red(client):
    # Writes directly to the shared test DB (api_usage has no delete endpoint — it's an
    # append-only log per CLAUDE.md > Data Model), so the row is removed again afterwards to
    # avoid leaking spend into other tests in this session.
    db = SessionLocal()
    row_id = None
    try:
        row = ApiUsage(
            model="claude-haiku-4-5",
            input_tokens=0,
            output_tokens=0,
            cost_usd_cents=get_spend_cap_usd_cents(),
            call_type="recipe_url",
        )
        db.add(row)
        db.commit()
        row_id = row.id

        resp = client.get("/api/v1/diagnostics/status")
        data = resp.json()["data"]

        assert data["claude_api"]["spend_cap_reached"] is True
        assert data["claude_api"]["state"] == "red"
        assert data["claude_api"]["remaining_usd_cents"] == 0.0
    finally:
        if row_id is not None:
            db.query(ApiUsage).filter(ApiUsage.id == row_id).delete()
            db.commit()
        db.close()


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

    # No api_usage rows exist in a fresh test DB, so Claude's indicator can't be green
    # yet — it's either grey (no key) or amber (key present, no calls made).
    assert data["claude_api"]["state"] in ("grey", "amber")
    assert data["claude_api"]["total_input_tokens"] == 0
    assert data["claude_api"]["total_output_tokens"] == 0
    assert data["claude_api"]["estimated_spend_usd"] == 0.0

    # Spend-cap fields (CLAUDE.md > Security > API Spend Cap) must always be present and
    # sane, regardless of whether any calls have been made yet.
    assert data["claude_api"]["spend_cap_reached"] is False
    assert data["claude_api"]["spend_cap_aud_cents"] > 0
    assert data["claude_api"]["spend_cap_usd_cents"] > 0
    assert data["claude_api"]["remaining_usd_cents"] == data["claude_api"]["spend_cap_usd_cents"]

    assert data["anylist"]["state"] in ("grey", "amber")


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

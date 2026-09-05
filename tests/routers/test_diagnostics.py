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

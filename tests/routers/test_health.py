"""Smoke test for GET /api/v1/health — see CLAUDE.md > Code Architecture &
Maintainability (every router gets at least a happy-path smoke test).
"""

from __future__ import annotations


def test_health_reports_ok_envelope_and_db_connected(client):
    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["database"]["connected"] is True


def test_health_reports_a_version_string(client):
    """2026-09-23 — client auto-update banner (static/js/update-banner.js) polls this field
    and compares it against the version it loaded with. See app/services/version.py."""
    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    version = resp.json()["data"]["version"]
    assert isinstance(version, str)
    assert version != ""

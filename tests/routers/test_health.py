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


def test_health_reports_the_build_identity_the_update_banner_compares(client):
    """The update banner (static/js/update-banner.js) compares `build_id` with the id stamped
    into the page it loaded; `version` is only the human label, `boot_id`/`started_at` identify
    this server process (Diagnostics). See app/services/version.py."""
    data = client.get("/api/v1/health").json()["data"]

    assert isinstance(data["build_id"], str) and len(data["build_id"]) >= 8
    assert isinstance(data["version"], str) and data["version"] != ""
    assert data["version_source"] in ("git", "unavailable")
    assert len(data["boot_id"]) == 12 and data["started_at"].endswith("+00:00")


def test_health_build_id_is_stable_across_requests_but_not_a_constant(client):
    a = client.get("/api/v1/health").json()["data"]
    b = client.get("/api/v1/health").json()["data"]
    assert (a["build_id"], a["boot_id"]) == (b["build_id"], b["boot_id"])
    assert a["build_id"] != "dev"


def test_health_is_never_cached(client):
    # a cached answer would hide exactly the change the banner exists to report
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"

"""POST /api/v1/client-log — the browser reports its own errors (2026-10-07 logging audit)."""

from __future__ import annotations

import logging

import pytest

from app.services import client_log


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    client_log.reset_rate_limits()
    yield
    client_log.reset_rate_limits()


def _post(client, **body):
    payload = {"kind": "error", "message": "boom", "url": "http://x/#/home"}
    payload.update(body)
    return client.post("/api/v1/client-log", json=payload)


def test_a_script_error_is_logged_at_error_under_app_client(client, caplog):
    with caplog.at_level(logging.INFO):
        resp = _post(client, message="x is not a function", stack="at foo (app.js:1:1)", build="abc123")

    assert resp.status_code == 200 and resp.json()["data"]["recorded"] is True
    (record,) = [r for r in caplog.records if r.name == "app.client"]
    assert record.levelno == logging.ERROR
    msg = record.getMessage()
    assert "x is not a function" in msg and "app.js:1:1" in msg and "abc123" in msg


def test_a_failed_request_is_only_a_warning(client, caplog):
    with caplog.at_level(logging.INFO):
        _post(client, kind="api", message="request failed: GET /api/v1/recipes")
    (record,) = [r for r in caplog.records if r.name == "app.client"]
    assert record.levelno == logging.WARNING


def test_query_string_is_stripped_and_line_breaks_cannot_forge_log_lines(client, caplog):
    with caplog.at_level(logging.INFO):
        _post(
            client,
            url="http://192.168.1.5:8000/?token=SECRET#/recipes",
            message="bad\n2026-01-01 00:00:00,000 [ERROR] app.fake: forged line",
        )
    msg = [r for r in caplog.records if r.name == "app.client"][0].getMessage()
    assert "SECRET" not in msg and "192.168.1.5" not in msg
    assert "\n" not in msg  # one report is exactly one log line
    assert "#/recipes" in msg


def test_oversized_fields_are_rejected_or_truncated(client, caplog):
    with caplog.at_level(logging.INFO):
        assert _post(client, message="m" * 3000).status_code == 422  # beyond the schema bound
        _post(client, message="m" * 1900, stack="s" * 15000)
    msg = [r for r in caplog.records if r.name == "app.client"][0].getMessage()
    assert len(msg) < 5000


def test_a_looping_page_is_rate_limited_and_still_gets_ok(client, caplog):
    with caplog.at_level(logging.INFO):
        results = [_post(client, message=f"e{i}").json()["data"]["recorded"] for i in range(30)]
    assert results.count(True) == client_log.RATE_LIMIT_PER_MINUTE
    assert results[-1] is False
    assert len([r for r in caplog.records if r.name == "app.client"]) == client_log.RATE_LIMIT_PER_MINUTE


def test_unknown_kind_is_treated_as_other(client, caplog):
    with caplog.at_level(logging.INFO):
        _post(client, kind="made-up")
    (record,) = [r for r in caplog.records if r.name == "app.client"]
    assert record.levelno == logging.WARNING

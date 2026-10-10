"""What the log says when something goes wrong (2026-10-07 logging audit).

Each test provokes one failure and asserts the log line carries enough to tell WHAT failed and
WHY — and, where it matters, that it does NOT carry something it must not (submitted values,
secrets). See docs/diagnostics-and-logging.md > "Failure logging".
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

import app.database as database
from app.main import app
from app.models.history import ShoppingHistory
from app.services.anylist_client import AnyListError


@pytest.fixture()
def boom_routes():
    """Temporary routes that raise on demand, removed afterwards (the app is a session singleton)."""
    before = len(app.router.routes)

    @app.get("/__test/anylist-boom")
    def _anylist():  # noqa: ANN202
        raise AnyListError("could not read the list: HTTP 503")

    @app.get("/__test/value-boom")
    def _value():  # noqa: ANN202
        raise ValueError("kaboom")

    yield
    del app.router.routes[before:]


def test_validation_error_logs_field_and_problem_but_never_the_submitted_value(client, caplog):
    with caplog.at_level(logging.INFO):
        resp = client.post("/api/v1/recipes", json={"name": ["TOP-SECRET-VALUE"]})

    assert resp.status_code == 422
    text = caplog.text
    assert "Validation error on POST /api/v1/recipes" in text
    assert "body.name" in text  # which field
    assert "TOP-SECRET-VALUE" not in text  # never the value


def test_unknown_route_is_logged_with_its_path(client, caplog):
    with caplog.at_level(logging.INFO):
        resp = client.get("/api/v1/definitely-not-a-route")

    assert resp.status_code == 404
    assert "HTTP 404 on GET /api/v1/definitely-not-a-route" in caplog.text


def test_anylist_failure_is_an_error_with_type_and_traceback(client, caplog, boom_routes):
    with caplog.at_level(logging.INFO):
        resp = client.get("/__test/anylist-boom")

    assert resp.status_code == 502 and resp.json()["error"]["code"] == "ANYLIST_FAILED"
    # the client never sees the raw text (Security §4) ...
    assert "HTTP 503" not in resp.text
    # ... the log does, at ERROR, with the exception type and a traceback
    (record,) = [r for r in caplog.records if "AnyList call failed" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert "AnyListError" in record.getMessage() and "HTTP 503" in record.getMessage()
    assert record.exc_info is not None


def test_unhandled_exception_is_logged_with_traceback_and_a_safe_response(boom_routes, caplog):
    with caplog.at_level(logging.INFO):
        resp = TestClient(app, raise_server_exceptions=False).get("/__test/value-boom")

    assert resp.status_code == 500 and "kaboom" not in resp.text
    (record,) = [r for r in caplog.records if "Unhandled exception" in r.getMessage()]
    assert record.levelno == logging.ERROR and record.exc_info[0] is ValueError


def test_corrupt_push_response_is_reported_unconfirmed_not_green(client, caplog):
    session = client.post("/api/v1/sessions", json={}).json()["data"]
    db = database.SessionLocal()
    try:
        db.add(
            ShoppingHistory(
                session_id=session["id"],
                items_json=json.dumps({"ingredients": []}),
                anylist_response_json="{this is not json",
            )
        )
        db.commit()
    finally:
        db.close()

    with caplog.at_level(logging.WARNING):
        resp = client.get("/api/v1/diagnostics/pushes")

    (push,) = resp.json()["data"]["pushes"]
    assert push["confirmed"] is False and push["response_unreadable"] is True
    assert "unreadable anylist_response_json" in caplog.text

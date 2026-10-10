"""A JavaScript error in the page reaches the server log (2026-10-07 logging audit).

Before this, a script error or unhandled rejection on the phone left no trace anywhere the
maintainer could read. static/js/error-report.js posts them to /api/v1/client-log; they show up in
Diagnostics > Recent errors.
"""

from __future__ import annotations

import time
import uuid


def _wait_for_log(api, needle: str, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entries = api.get("/api/v1/diagnostics/logs", params={"level": "ERROR", "limit": 200}).json()["data"]["entries"]
        hits = [e for e in entries if needle in e["message"]]
        if hits:
            return hits[0]
        time.sleep(0.1)
    return None


def test_an_uncaught_script_error_and_an_unhandled_rejection_reach_the_server_log(browser, api):
    marker = uuid.uuid4().hex[:10]
    browser.wait_for(".nav-item")
    browser.eval(f"setTimeout(function () {{ throw new Error('cdp-uncaught-{marker}'); }}, 0); true")
    browser.eval(f"Promise.reject(new Error('cdp-rejected-{marker}')); true")

    uncaught = _wait_for_log(api, f"cdp-uncaught-{marker}")
    rejected = _wait_for_log(api, f"cdp-rejected-{marker}")

    assert uncaught is not None, "the uncaught error never reached the server log"
    assert uncaught["logger"] == "app.client" and "Browser error" in uncaught["message"]
    assert rejected is not None, "the unhandled rejection never reached the server log"
    assert "Browser unhandledrejection" in rejected["message"]

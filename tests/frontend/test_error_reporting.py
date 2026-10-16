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


def test_copy_errors_works_without_the_async_clipboard_and_shows_a_box_when_every_way_fails(browser, server_url):
    """Firefox on a phone over plain HTTP has no `navigator.clipboard` (2026-10-16). Headless runs
    on 127.0.0.1, a secure context, so the missing API is simulated."""
    entry = {"time": "2026-10-17T05:41:00", "level": "ERROR", "logger": "app.client",
             "message": "Browser error on /#/diagnostics", "traceback": None}
    browser.navigate(f"{server_url}/#/diagnostics")
    browser.wait_for("#diag-status")
    browser.eval(
        "Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true});"
        "window.api.diagnostics.recentErrors = function(){ return Promise.resolve({entries: [" + __import__("json").dumps(entry) + "]}); };"
        "window.__copied = []; document.execCommand = function(){ window.__copied.push(document.activeElement.value); return true; };"
    )
    browser.navigate(f"{server_url}/#/home")  # re-mount so the stub is what the view loads
    browser.navigate(f"{server_url}/#/diagnostics")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not browser.eval("!!document.querySelector('#diag-errors .log-line')"):
        time.sleep(0.1)

    browser.click("button", contains="Copy errors")
    assert "Browser error on /#/diagnostics" in browser.eval("window.__copied[0] || ''")
    assert browser.eval("document.querySelector('.copy-fallback').closest('[hidden]') !== null")  # box stays hidden

    browser.eval("document.execCommand = function(){ return false; }; true")
    browser.click("button", contains="Copy errors")
    assert browser.eval("document.querySelector('.copy-fallback').closest('[hidden]') === null")
    assert "Browser error on /#/diagnostics" in browser.eval("document.querySelector('.copy-fallback').value")
    assert not browser.console_errors()


def test_a_muted_cross_origin_script_error_is_reported_as_a_warning_not_an_error(browser, api):
    marker = uuid.uuid4().hex[:10]
    browser.wait_for(".nav-item")
    # What a browser extension's failure looks like to the page: no filename, no Error object.
    browser.eval(
        "window.dispatchEvent(new ErrorEvent('error', {message: 'Script error.'}));"
        f"window.ErrorReport.report('other', 'marker-{marker}'); true"
    )
    deadline = time.monotonic() + 8
    entries = []
    while time.monotonic() < deadline:
        entries = api.get("/api/v1/diagnostics/logs", params={"level": "WARNING", "limit": 200}).json()["data"]["entries"]
        if any("outside the app" in e["message"] for e in entries):
            break
        time.sleep(0.1)
    hit = next(e for e in entries if "outside the app" in e["message"])
    assert hit["level"] == "WARNING"

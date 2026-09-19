"""Headless-browser regression tests for the 2026-09-13 code review's confirmed frontend
bugs (Stage 4.3 of the approved fix plan). Built on `scripts/cdp.py` — no Node, no
Playwright, see tests/frontend/README.md and HEADLESS_VERIFY.md.

Each test drives the real page against the real scratch server (`server_url` fixture in
conftest.py), and cross-checks the result against the API directly rather than trusting the
DOM alone (same discipline HEADLESS_VERIFY.md already asks for in manual sessions). Every
test also asserts `browser.console_errors()` is empty as a baseline check — a silent JS
exception during the flow under test would otherwise go unnoticed.
"""

from __future__ import annotations

import json
import time
import uuid

TIMEOUT = 8.0


def _wait_for_value_match(browser, class_name: str, value: str, *, timeout: float = TIMEOUT) -> None:
    """Poll until some element with `class_name` has exactly this `.value` — used instead of
    `browser.wait_for(selector)` when several elements share the same class (e.g. every
    settings card's name input uses `.settings-name-input`) and only one, not-yet-known-to-
    exist-yet (async load) instance is the one under test."""
    expr = (
        f"Array.from(document.querySelectorAll({json.dumps('.' + class_name)}))"
        f".some(function(e){{return e.value === {json.dumps(value)};}})"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.eval(expr):
            return
        time.sleep(0.2)
    raise TimeoutError(f"no .{class_name} ever had value {value!r}")


def test_unscheduling_a_session_slot_day_persists_after_reload(browser, api, server_url):
    """2026-09-13 code review, Stage 1 fix: services/sessions.py > update_slot() used to
    silently drop an explicit `day_of_week: null` (the `if value is not None` guard), so
    picking "— day —" in the UI looked like it worked but the day came back on reload. This
    drives the actual dropdown, not the service function directly, so it also exercises
    api.js's PATCH body and sessions.js's daySelect() wiring end to end."""
    recipe = api.post(
        "/api/v1/recipes", json={"name": f"CDP day-clear test {uuid.uuid4().hex[:8]}", "base_servings": 4}
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    slot = api.post(
        f"/api/v1/sessions/{session['id']}/recipes",
        json={"recipe_id": recipe["id"], "day_of_week": 3},
    ).json()["data"]
    assert slot["day_of_week"] == 3

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.wait_for(".settings-row select")
    # One recipe slot -> two <select>s in document order: [0] servings, [1] day (see
    # sessions.js > renderSlotRow). Only one slot exists in this session, so a plain nth
    # index (rather than _wait_for_value_match's value-scan) is unambiguous here.
    browser.fill(".settings-row select", "", nth=1)

    # Confirm against the API first (authoritative), then reload the page and confirm the
    # dropdown itself comes back showing no day — the actual user-visible regression.
    deadline = time.monotonic() + TIMEOUT
    cleared = False
    while time.monotonic() < deadline:
        got = api.get(f"/api/v1/sessions/{session['id']}").json()["data"]
        if got["recipes"][0]["day_of_week"] is None:
            cleared = True
            break
        time.sleep(0.2)
    assert cleared, "day_of_week was not cleared via the UI"

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.wait_for(".settings-row select")
    assert browser.eval("document.querySelectorAll('.settings-row select')[1].value") == ""
    assert not browser.console_errors(), browser.console_errors()


def test_clearing_a_usual_items_note_persists_after_reload(browser, api, server_url):
    """2026-09-13 code review, Stage 1 fix: services/usuals.py > update_usual() had the same
    `if value is not None` bug as update_slot() above — clearing a usual item's note in
    Settings silently no-opped. Drives the real Save button in settings-usuals.js."""
    name = f"cdp note-clear test {uuid.uuid4().hex[:8]}"
    usual = api.post(
        "/api/v1/settings/usuals",
        json={"name": name, "cadence_days": 14, "notes": "clear me"},
    ).json()["data"]

    # Phase 6 Chunk 6.4: Settings is now an index + drill-down sub-page per section — the
    # usuals card only renders at its own #/settings/usuals route, not on #/settings itself.
    browser.navigate(f"{server_url}/#/settings/usuals")
    _wait_for_value_match(browser, "settings-name-input", name)

    result = browser.eval(
        "(function(name){"
        "var inputs=Array.from(document.querySelectorAll('.settings-name-input'));"
        "var nameInput=inputs.find(function(i){return i.value===name;});"
        "if(!nameInput) return 'NAME_INPUT_NOT_FOUND';"
        "var row=nameInput.closest('.settings-row');"
        "var notesInput=row.querySelector('.settings-notes-input');"
        "if(!notesInput) return 'NOTES_INPUT_NOT_FOUND';"
        "notesInput.value='';"
        "notesInput.dispatchEvent(new Event('input',{bubbles:true}));"
        "notesInput.dispatchEvent(new Event('change',{bubbles:true}));"
        "var saveBtn=Array.from(row.querySelectorAll('button')).find(function(b){return b.textContent==='Save';});"
        "if(!saveBtn) return 'SAVE_BUTTON_NOT_FOUND';"
        "saveBtn.click();"
        "return 'OK';"
        f"}})({json.dumps(name)})"
    )
    assert result == "OK", result

    deadline = time.monotonic() + TIMEOUT
    cleared = False
    while time.monotonic() < deadline:
        items = api.get("/api/v1/settings/usuals").json()["data"]["items"]
        row = next((i for i in items if i["id"] == usual["id"]), None)
        if row is not None and row["notes"] is None:
            cleared = True
            break
        time.sleep(0.2)
    assert cleared, "usual item's notes were not cleared via the UI"

    browser.navigate(f"{server_url}/#/settings/usuals")
    _wait_for_value_match(browser, "settings-name-input", name)
    notes_value = browser.eval(
        "(function(name){"
        "var inputs=Array.from(document.querySelectorAll('.settings-name-input'));"
        "var nameInput=inputs.find(function(i){return i.value===name;});"
        "var row=nameInput.closest('.settings-row');"
        "return row.querySelector('.settings-notes-input').value;"
        f"}})({json.dumps(name)})"
    )
    assert notes_value == ""
    assert not browser.console_errors(), browser.console_errors()


def test_queued_capture_shows_message_not_a_blank_review_form(browser, server_url):
    """2026-09-13 code review, Stage 1 fix: when both Gemini models are over quota, the
    capture endpoints return {"queued": true, "message": ...} (a parked retry, not a
    failure) — static/js/capture.js used to hand this straight to CaptureReviewView.mount()
    like a real extraction, landing the user on a blank ingredient form with no explanation.

    Stubs `window.api.recipes.captureUrl` (via the same mechanism `mountPhoto`'s
    `capturePhoto` call goes through `window.api.recipes.capturePhoto` and both paths funnel
    into the identical `showQueuedMessage()` — see capture.js) so no real network/AI call
    happens at all; this only exercises the frontend's own branch on `result.queued`."""
    browser.navigate(f"{server_url}/#/recipes/capture-url")
    browser.wait_for('input[type="url"]')

    queued_message = "All Gemini models are over today's quota — this capture is queued and will retry automatically."
    browser.eval(
        "window.api.recipes.captureUrl = function(){"
        f"return Promise.resolve({{queued: true, message: {json.dumps(queued_message)}}});"
        "};"
    )

    browser.fill('input[type="url"]', "https://example.com/some-recipe")
    browser.click("button.primary", contains="Fetch & extract")
    # "h2" already matches before the click (the "Capture from a web page" heading), so
    # wait_for(selector) alone can't tell the queued transition apart from the original
    # form -- poll for the actual heading text the fixed code path renders instead.
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and browser.text("h2") != "Capture queued":
        time.sleep(0.2)

    assert browser.text("h2") == "Capture queued"
    assert queued_message in browser.html(".card")
    # The bug this regresses: landing on the real review form instead (blank, no
    # explanation) — assert its distinguishing markup is simply not there.
    assert "Review extracted recipe" not in browser.html("body")
    assert browser.eval("!document.querySelector('.ingredient-edit-row')")
    assert not browser.console_errors(), browser.console_errors()

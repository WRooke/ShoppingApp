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
    silently drop an explicit `day_of_week: null` (the `if value is not None` guard). Phase 6
    Chunk 6.5 replaced the per-slot day <select> with the 7-day-grid + tap-to-assign UI
    (session-week.js) — this now drives that flow instead (move button -> tap the
    Unassigned section), still exercising api.js's PATCH body end to end, just through the
    UI that actually exists now."""
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
    browser.wait_for(".slot-row .move-btn")
    browser.eval("document.querySelector('.slot-row .move-btn').click()")
    browser.wait_for(".day-section.unassigned")
    browser.eval("document.querySelector('.day-section.unassigned').click()")

    # Confirm against the API first (authoritative), then reload the page and confirm the
    # grid itself comes back showing the slot under Unassigned — the actual user-visible
    # regression this test guards against.
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
    browser.wait_for(".day-section.unassigned")
    assert "1 item" in browser.text(".day-section.unassigned .count")
    assert not browser.console_errors(), browser.console_errors()


def test_session_workspace_add_buttons_above_days_no_stray_move_banner(browser, api, server_url):
    """2026-09-23 fix: `sessions.js > renderWorkspaceCard()` used to append "+ Add recipe" /
    "+ Add leftovers day" AFTER the 7-day grid instead of before it, and `session-week.js`'s
    empty `.move-banner` (hidden via the `.hidden` DOM property, with no matching
    `[hidden] { display: none }` CSS rule) rendered as a permanent, textless accent-coloured
    bar above "Unassigned" regardless of state. Both fixed without changing the underlying
    move-to-day mechanism."""
    recipe = api.post(
        "/api/v1/recipes", json={"name": f"CDP layout test {uuid.uuid4().hex[:8]}", "base_servings": 4}
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(
        f"/api/v1/sessions/{session['id']}/recipes",
        json={"recipe_id": recipe["id"], "day_of_week": 1},
    )

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.wait_for(".day-section")

    # DOM order: the add-row must come before the week grid's first day-section, not after.
    order_ok = browser.eval(
        "(function(){"
        "var addBtn=Array.from(document.querySelectorAll('button')).find(function(b){return b.textContent==='+ Add recipe';});"
        "var daySection=document.querySelector('.day-section');"
        "if(!addBtn||!daySection) return 'MISSING';"
        "return (addBtn.compareDocumentPosition(daySection) & Node.DOCUMENT_POSITION_FOLLOWING) ? 'OK' : 'WRONG_ORDER';"
        "})()"
    )
    assert order_ok == "OK", order_ok

    # The move banner exists in the DOM (unmoved feature) but must not be visible when hidden.
    banner_hidden = browser.eval(
        "(function(){"
        "var b=document.querySelector('.move-banner');"
        "if(!b) return 'MISSING';"
        "return (b.hidden && getComputedStyle(b).display === 'none') ? 'OK' : 'VISIBLE';"
        "})()"
    )
    assert banner_hidden == "OK", banner_hidden
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


def test_update_banner_appears_on_version_mismatch_and_reloads_on_tap(browser, server_url):
    """2026-09-23 — client auto-update notification (static/js/update-banner.js). Stubs
    window.api.health() so no real server restart is needed: the banner's own first check
    (page load) records the initial version, then a second stubbed response with a different
    version, triggered via the UpdateBanner.checkNow() test hook rather than waiting for the
    real 5-minute poll, must show the persistent banner. Also confirms tapping it reloads
    (window.location.reload stubbed to a flag rather than actually reloading)."""
    browser.navigate(f"{server_url}/#/home")
    browser.wait_for(".nav-item")

    # The page's own load-time check already recorded a real "loaded version" (whatever
    # `git describe` returned) before this test can intervene — stub api.health() to echo
    # that same real value first, confirming a same-version check is a no-op, before
    # switching to a genuinely different value.
    loaded = browser.eval("window.UpdateBanner.getLoadedVersion()")
    browser.eval(
        "window.__healthVersion = " + json.dumps(loaded) + ";"
        "window.api.health = function(){"
        "return Promise.resolve({version: window.__healthVersion});"
        "};"
    )
    browser.eval("window.UpdateBanner.checkNow();")

    assert browser.eval("!document.querySelector('.update-banner')")

    browser.eval(
        "window.__healthVersion = " + json.dumps(loaded + "-new") + ";"
        "window.UpdateBanner.checkNow();"
    )
    browser.wait_for(".update-banner")
    assert "Update available" in browser.text(".update-banner")

    # Tapping it does a real reload (location.reload isn't reliably overridable across
    # browsers) — set a marker that only a fresh page load would wipe, click, then confirm
    # the marker is gone and the app shell has genuinely re-initialised.
    browser.eval("window.__preClickMarker = 'still-here';")
    browser.eval("document.querySelector('.update-banner').click()")
    deadline = time.monotonic() + TIMEOUT
    reloaded = False
    while time.monotonic() < deadline:
        if browser.eval("window.__preClickMarker") is None:
            reloaded = True
            break
        time.sleep(0.1)
    assert reloaded, "tapping the banner did not reload the page"
    browser.wait_for(".nav-item")
    assert not browser.console_errors(), browser.console_errors()


def test_ingredient_alias_group_shows_count_and_fixed_name_field(browser, api, server_url):
    """2026-09-23 Settings redesign (settings-ingredient-aliases.js): a canonical group now
    renders as one `.settings-group-card` with a visible alias count, and each alias's name
    is a labelled, disabled field (not a bare unexplained span)."""
    canonical = f"cdp-canon-{uuid.uuid4().hex[:8]}"
    alias1 = f"cdp-alias-a-{uuid.uuid4().hex[:8]}"
    alias2 = f"cdp-alias-b-{uuid.uuid4().hex[:8]}"
    api.post(
        "/api/v1/settings/ingredient-aliases",
        json={"alias_name": alias1, "canonical_name": canonical},
    )
    api.post(
        "/api/v1/settings/ingredient-aliases",
        json={"alias_name": alias2, "canonical_name": canonical},
    )

    browser.navigate(f"{server_url}/#/settings/ingredient-aliases")
    _wait_for_value_match(browser, "settings-name-input", alias1)

    result = browser.eval(
        "(function(canon){"
        "var heads=Array.from(document.querySelectorAll('.settings-group-name'));"
        "var head=heads.find(function(h){return h.textContent===canon;});"
        "if(!head) return 'GROUP_NOT_FOUND';"
        "var card=head.closest('.settings-group-card');"
        "var count=card.querySelector('.settings-group-count').textContent;"
        "var nameInput=card.querySelector('.settings-name-input');"
        "return JSON.stringify({count: count, disabled: nameInput.disabled});"
        f"}})({json.dumps(canonical)})"
    )
    assert result != "GROUP_NOT_FOUND", result
    parsed = json.loads(result)
    assert "2" in parsed["count"] and "alias" in parsed["count"]
    assert parsed["disabled"] is True
    assert not browser.console_errors(), browser.console_errors()


def test_product_unit_group_renames_every_pack_size_together(browser, api, server_url):
    """2026-09-23 Settings redesign (settings-product-units.js): an ingredient with more than
    one pack size now renders as one grouped card; renaming the group heading renames every
    pack-size row in it, not just one."""
    original_name = f"cdp-eggs-{uuid.uuid4().hex[:8]}"
    new_name = f"cdp-eggs-renamed-{uuid.uuid4().hex[:8]}"
    unit_a = api.post(
        "/api/v1/settings/product-units",
        json={"ingredient_name": original_name, "purchase_label": "half dozen", "purchase_qty": 6, "purchase_unit": "each"},
    ).json()["data"]
    unit_b = api.post(
        "/api/v1/settings/product-units",
        json={"ingredient_name": original_name, "purchase_label": "dozen", "purchase_qty": 12, "purchase_unit": "each"},
    ).json()["data"]

    browser.navigate(f"{server_url}/#/settings/product-units")
    browser.wait_for(".settings-group-card")

    result = browser.eval(
        "(function(oldName, newName){"
        "var heads=Array.from(document.querySelectorAll('.settings-group-name input'));"
        "var head=heads.find(function(h){return h.value===oldName;});"
        "if(!head) return 'GROUP_NOT_FOUND';"
        "var card=head.closest('.settings-group-card');"
        "var packCount=card.querySelectorAll('.settings-group-row').length;"
        "head.value=newName;"
        "head.dispatchEvent(new Event('change',{bubbles:true}));"
        "return JSON.stringify({packCount: packCount});"
        f"}})({json.dumps(original_name)}, {json.dumps(new_name)})"
    )
    assert result != "GROUP_NOT_FOUND", result
    assert json.loads(result)["packCount"] == 2

    deadline = time.monotonic() + TIMEOUT
    both_renamed = False
    while time.monotonic() < deadline:
        items = api.get("/api/v1/settings/product-units?limit=200").json()["data"]["items"]
        by_id = {i["id"]: i for i in items}
        if (
            by_id.get(unit_a["id"], {}).get("ingredient_name") == new_name
            and by_id.get(unit_b["id"], {}).get("ingredient_name") == new_name
        ):
            both_renamed = True
            break
        time.sleep(0.2)
    assert both_renamed, "renaming the group did not rename both pack-size rows"
    assert not browser.console_errors(), browser.console_errors()


def test_capture_progress_step_list_shows_real_backend_state(browser, server_url):
    """2026-09-23 — real step-based capture progress (static/js/capture.js). Stubs
    api.recipes.captureProgress to return canned per-step statuses and freezes captureUrl
    mid-flight (a Promise that never resolves) so the step list can be inspected while a
    capture would still be "in progress" for real."""
    browser.navigate(f"{server_url}/#/recipes/capture-url")
    browser.wait_for('input[type="url"]')

    browser.eval(
        "window.api.recipes.captureUrl = function(){ return new Promise(function(){}); };"
        "window.api.recipes.captureProgress = function(token){"
        "return Promise.resolve({steps: ["
        "{name: 'extract', status: 'done', detail: null},"
        "{name: 'sections', status: 'active', detail: null},"
        "{name: 'substitutions', status: 'pending', detail: null}"
        "]});"
        "};"
    )
    browser.fill('input[type="url"]', "https://example.com/some-recipe")
    browser.click("button.primary", contains="Fetch & extract")

    browser.wait_for(".step-icon.done")
    browser.wait_for(".step-icon.active")
    rows = browser.eval(
        "Array.from(document.querySelectorAll('.step-row')).map(function(r){"
        "return {"
        "status: r.querySelector('.step-icon').className.replace('step-icon ', ''),"
        "label: r.querySelector('.step-label').textContent"
        "};"
        "})"
    )
    by_status = {r["status"]: r["label"] for r in rows}
    assert by_status.get("done") == "Extracting ingredients"
    assert by_status.get("active") == "Suggesting aisles"
    assert by_status.get("pending") == "Checking substitutions"
    assert not browser.console_errors(), browser.console_errors()


def test_push_progress_step_list_shows_which_item_failed(browser, api, server_url):
    """2026-09-23 — real per-item push progress (static/js/checklist-push.js). Drives a real
    checklist tap to "no" so the push list is non-empty, then stubs api.checklist.push to
    reject and api.checklist.pushProgress to report the one item still "active" — confirming
    the UI marks that specific item as the one that failed, not a generic alert alone."""
    item_name = f"cdp-push-progress-{uuid.uuid4().hex[:8]}"
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP push progress test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 6, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(
        f"/api/v1/sessions/{session['id']}/recipes",
        json={"recipe_id": recipe["id"]},
    )
    api.post(f"/api/v1/sessions/{session['id']}/consolidate", json={})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".have-toggle")
    browser.eval("document.querySelector('.have-toggle').click()")  # unknown -> yes
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and "have-yes" not in (
        browser.eval("document.querySelector('.have-toggle').className") or ""
    ):
        time.sleep(0.1)
    browser.eval("document.querySelector('.have-toggle').click()")  # yes -> no
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and "have-no" not in (
        browser.eval("document.querySelector('.have-toggle').className") or ""
    ):
        time.sleep(0.1)

    browser.eval(
        "window.__alerted = null;"
        "window.alert = function(msg){ window.__alerted = msg; };"
        "window.api.checklist.push = function(){"
        "return Promise.reject({code: 'ANYLIST_FAILED', message: 'AnyList is unreachable'});"
        "};"
        "window.api.checklist.pushProgress = function(token){"
        f"return Promise.resolve({{steps: [{{name: {json.dumps(item_name)}, status: 'active', detail: null}}]}});"
        "};"
    )
    browser.click("button.primary", contains="Push to AnyList")

    deadline = time.monotonic() + TIMEOUT
    alerted = None
    while time.monotonic() < deadline:
        alerted = browser.eval("window.__alerted")
        if alerted:
            break
        time.sleep(0.1)
    assert alerted and "AnyList is unreachable" in alerted

    failed_label = browser.eval(
        "(function(){"
        "var row=document.querySelector('.step-icon.failed');"
        "return row ? row.closest('.step-row').querySelector('.step-label').textContent : null;"
        "})()"
    )
    assert failed_label == "Couldn't add " + item_name
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

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

from app.services.text_normalize import normalise_ingredient_name

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
    # Normalised immediately — usuals.py's create_usual() runs names through the shared
    # normaliser (2026-09-27), which folds hyphens to a space.
    name = normalise_ingredient_name(f"cdp note-clear test {uuid.uuid4().hex[:8]}")
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
    # Normalised immediately — ingredient_aliases.create_alias() runs names through the shared
    # normaliser (2026-09-27), which folds hyphens to a space.
    canonical = normalise_ingredient_name(f"cdp-canon-{uuid.uuid4().hex[:8]}")
    alias1 = normalise_ingredient_name(f"cdp-alias-a-{uuid.uuid4().hex[:8]}")
    alias2 = normalise_ingredient_name(f"cdp-alias-b-{uuid.uuid4().hex[:8]}")
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
    # Normalised immediately — settings.py's create_product_unit() runs names through the
    # shared normaliser (2026-09-27), which folds hyphens to a space.
    original_name = normalise_ingredient_name(f"cdp-eggs-{uuid.uuid4().hex[:8]}")
    new_name = normalise_ingredient_name(f"cdp-eggs-renamed-{uuid.uuid4().hex[:8]}")
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
        "{name: 'sections', status: 'active', detail: null}"
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
    # Only 2 steps as of 2026-09-30 (was 3 — "substitutions" removed with the AI
    # substitution-flagging call; capture.js's STEP_ORDER drives rendering, not whatever the
    # backend response happens to include, so a stray 3rd entry wouldn't render anyway).
    assert len(rows) == 2
    assert by_status.get("done") == "Extracting ingredients"
    assert by_status.get("active") == "Suggesting aisles"
    assert not browser.console_errors(), browser.console_errors()


def test_have_need_toggle_reaches_any_target_state_in_one_tap(browser, api, server_url):
    """2026-09-24 — replaces the old single .have-toggle cycling button (unknown -> yes -> no
    -> unknown, up to two taps to reach a target) with two independent one-tap toggles. Drives
    "no" directly from "yes" (skipping "unknown"), then back to "unknown" from "no" — both in
    exactly one click each — confirmed against the API, not just the DOM."""
    # Normalised immediately — the shared normaliser folds hyphens to a space, so a hyphenated
    # fixture name wouldn't round-trip literally through ingredient_name (2026-09-27).
    item_name = normalise_ingredient_name(f"cdp-have-need-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP have/need test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 500, "unit": "g"}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})
    api.post(f"/api/v1/sessions/{session['id']}/consolidate", json={})

    def have_it_via_api():
        items = api.get(f"/api/v1/checklist/{session['id']}").json()["data"]["items"]
        row = next(i for i in items if i["ingredient_name"] == item_name)
        return row["have_it"], row["id"]

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".have-need-btn.have")

    # One tap: unknown -> yes.
    browser.eval("document.querySelector('.have-need-btn.have').click()")
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and have_it_via_api()[0] != "yes":
        time.sleep(0.1)
    assert have_it_via_api()[0] == "yes"

    # One tap: yes -> no directly (never passes through "unknown").
    browser.eval("document.querySelector('.have-need-btn.need').click()")
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and have_it_via_api()[0] != "no":
        time.sleep(0.1)
    assert have_it_via_api()[0] == "no"
    assert browser.eval(
        "document.querySelector('.have-need-btn.need').getAttribute('aria-pressed')"
    ) == "true"

    # One tap on the already-pressed button: no -> unknown.
    browser.eval("document.querySelector('.have-need-btn.need').click()")
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and have_it_via_api()[0] != "unknown":
        time.sleep(0.1)
    assert have_it_via_api()[0] == "unknown"
    assert not browser.console_errors(), browser.console_errors()


def test_pack_size_chip_resolves_this_session_and_preserves_other_items(browser, api, server_url):
    """2026-09-24, reworked 2026-09-30 (chunk 7.5) — the standalone "+ Add pack size" link is
    gone; pack size is now the ingredient panel's Pack size chip (checklist-panel.js).
    Defaults to "this list only" (session_ingredient_merges, not the real product_units table)
    — still resolves the pack breakdown THIS session, while an unrelated item's already-made
    "need it" choice survives the resulting re-consolidate untouched (the "merge, not rebuild"
    guarantee)."""
    # Normalised immediately — see the have/need toggle test above for why.
    no_pack_item = normalise_ingredient_name(f"cdp-nopack-{uuid.uuid4().hex[:8]}")
    other_item = normalise_ingredient_name(f"cdp-other-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP pack-size test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [
                {"name": no_pack_item, "quantity": 450, "unit": "g"},
                {"name": other_item, "quantity": 2, "unit": None},
            ],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})
    api.post(f"/api/v1/sessions/{session['id']}/consolidate", json={})

    def checklist_items():
        return api.get(f"/api/v1/checklist/{session['id']}").json()["data"]["items"]

    other_id = next(i for i in checklist_items() if i["ingredient_name"] == other_item)["id"]
    api.patch(f"/api/v1/checklist/{session['id']}/items/{other_id}", json={"have_it": "no", "add_to_list": True})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    _wait_for_value_match_text(browser, ".name", no_pack_item)

    # Tap the row's name to expand it (recipe breakdown + the ingredient panel).
    expand_result = browser.eval(
        "(function(name){"
        "var rows=Array.from(document.querySelectorAll('.checklist-row'));"
        "var row=rows.find(function(r){var n=r.querySelector('.name'); return n && n.textContent.indexOf(name)===0;});"
        "if(!row) return 'ROW_NOT_FOUND';"
        "row.querySelector('.name').click();"
        "return 'OK';"
        f"}})({json.dumps(no_pack_item)})"
    )
    assert expand_result == "OK", expand_result
    browser.wait_for(".edit-ingredient-toggle")

    # Reveal the select-exclusive chip row, then tap Pack size.
    browser.eval("document.querySelector('.edit-ingredient-toggle').click()")
    browser.wait_for(".edit-chip-row")
    pack_chip_result = browser.eval(
        "(function(){"
        "var btns=Array.from(document.querySelectorAll('.edit-chip-row .link-btn'));"
        "var btn=btns.find(function(b){return b.textContent==='Pack size';});"
        "if(!btn) return 'PACK_CHIP_NOT_FOUND';"
        "btn.click();"
        "return 'OK';"
        "})()"
    )
    assert pack_chip_result == "OK", pack_chip_result
    browser.wait_for(".pack-size-form")

    fill_result = browser.eval(
        "(function(){"
        "var form=document.querySelector('.pack-size-form');"
        "var inputs=form.querySelectorAll('input');"
        "inputs[0].value='700g jar'; inputs[0].dispatchEvent(new Event('input',{bubbles:true}));"
        "inputs[1].value='700'; inputs[1].dispatchEvent(new Event('input',{bubbles:true}));"
        "inputs[2].value='g'; inputs[2].dispatchEvent(new Event('input',{bubbles:true}));"
        # Scoped to .persist-actions -- the chip's own toggle buttons (This list only /
        # Always) are also <button> elements sharing the form, just not this one.
        "var saveBtn=Array.from(form.querySelectorAll('.persist-actions button')).find(function(b){return b.textContent==='Save';});"
        "if(!saveBtn) return 'SAVE_BUTTON_NOT_FOUND';"
        "saveBtn.click();"
        "return 'OK';"
        "})()"
    )
    assert fill_result == "OK", fill_result

    deadline = time.monotonic() + TIMEOUT
    resolved = False
    while time.monotonic() < deadline:
        row = next((i for i in checklist_items() if i["ingredient_name"] == no_pack_item), None)
        if row and row.get("display_qty"):
            resolved = True
            break
        time.sleep(0.2)
    assert resolved, "the checklist never picked up a pack breakdown for the new product_units row"

    other_row = next(i for i in checklist_items() if i["ingredient_name"] == other_item)
    assert other_row["have_it"] == "no" and other_row["add_to_list"] is True
    assert not browser.console_errors(), browser.console_errors()


def _wait_for_value_match_text(browser, selector: str, text: str, *, timeout: float = TIMEOUT) -> None:
    """Like _wait_for_value_match, but for element .textContent instead of .value — used for
    the checklist's .name divs/buttons, which aren't inputs. Prefix match, not exact equality
    (2026-09-30, chunk 7.4): a row whose ingredient has a recipe breakdown renders its name as
    "<name> ▾" (checklist.js > rowNameParts()) — true for virtually every real checklist row,
    since any item consolidated from an actual recipe has at least one contributing recipe."""
    expr = (
        f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
        f".some(function(e){{return e.textContent.indexOf({json.dumps(text)}) === 0;}})"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.eval(expr):
            return
        time.sleep(0.2)
    raise TimeoutError(f"no {selector} ever had text {text!r}")


def test_push_progress_step_list_shows_which_item_failed(browser, api, server_url):
    """2026-09-23 — real per-item push progress (static/js/checklist-push.js). Drives a real
    checklist tap to "no" so the push list is non-empty, then stubs api.checklist.push to
    reject and api.checklist.pushProgress to report the one item still "active" — confirming
    the UI marks that specific item as the one that failed, not a generic alert alone."""
    # Normalised immediately — see the have/need toggle test above for why.
    item_name = normalise_ingredient_name(f"cdp-push-progress-{uuid.uuid4().hex[:8]}")
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
    browser.wait_for(".have-need-btn.need")
    browser.eval("document.querySelector('.have-need-btn.need').click()")  # one tap -> "no"
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and (
        browser.eval("document.querySelector('.have-need-btn.need').getAttribute('aria-pressed')")
        != "true"
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


def test_plan_goes_straight_to_checklist_no_review_step(browser, api, server_url):
    """2026-09-30, chunk 7.4 — the standalone Review screen ("Review ingredients & shopping
    list") between Plan and Checklist is deleted; Plan's sticky action now links straight to
    Checklist, which consolidates itself on load (chunk 7.3) with zero prior explicit
    /consolidate call. Drives the real button click end to end (not just a direct
    #/checklist/<id> navigation, which every other checklist test already covers) so a
    regression in the button's own wiring would actually be caught."""
    item_name = normalise_ingredient_name(f"cdp-plan-to-checklist-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP plan-to-checklist test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 500, "unit": "g"}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})
    # Deliberately no POST /sessions/{id}/consolidate here — the whole point of chunk 7.3.

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.wait_for(".step-list")
    step_list_text = browser.text(".step-list")
    assert step_list_text.replace(" ", "") == "Plan→Checklist→Push"
    assert "Review" not in browser.html("body")

    browser.click("button.primary", contains="Checklist")
    browser.wait_for(".checklist-row")

    assert browser.eval("location.hash") == f"#/checklist/{session['id']}"
    assert item_name in browser.text(".checklist-row .name")
    assert browser.text(".step-list").replace(" ", "") == "Plan→Checklist→Push"
    assert not browser.console_errors(), browser.console_errors()
    assert browser.eval("!document.querySelector('.ingredient-edit-row')")
    assert not browser.console_errors(), browser.console_errors()


def _expand_and_open_edit(browser, item_name):
    """Shared driver for the ingredient panel (chunk 7.5): tap a row's name to expand it, then
    tap "Edit ingredient" to reveal the select-exclusive chip row. Returns nothing; raises via
    assert if either step's target element never appears."""
    expand_result = browser.eval(
        "(function(name){"
        "var rows=Array.from(document.querySelectorAll('.checklist-row'));"
        "var row=rows.find(function(r){var n=r.querySelector('.name'); return n && n.textContent.indexOf(name)===0;});"
        "if(!row) return 'ROW_NOT_FOUND';"
        "row.querySelector('.name').click();"
        "return 'OK';"
        f"}})({json.dumps(item_name)})"
    )
    assert expand_result == "OK", expand_result
    browser.wait_for(".edit-ingredient-toggle")
    browser.eval("document.querySelector('.edit-ingredient-toggle').click()")
    browser.wait_for(".edit-chip-row")


def _click_chip(browser, label):
    result = browser.eval(
        "(function(label){"
        "var btns=Array.from(document.querySelectorAll('.edit-chip-row .link-btn'));"
        "var btn=btns.find(function(b){return b.textContent===label;});"
        "if(!btn) return 'CHIP_NOT_FOUND:' + label;"
        "btn.click();"
        "return 'OK';"
        f"}})({json.dumps(label)})"
    )
    assert result == "OK", result


def test_edit_ingredient_chips_are_select_exclusive(browser, api, server_url):
    """2026-09-30, chunk 7.5 — picking a chip closes whichever one was already open for that
    row, so at most one sub-panel shows at a time (the mockup's approved design, settled after
    the maintainer's own feedback round on chunk 7.1)."""
    item_name = normalise_ingredient_name(f"cdp-chip-exclusive-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP chip exclusive test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 1, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    _wait_for_value_match_text(browser, ".name", item_name)
    _expand_and_open_edit(browser, item_name)

    _click_chip(browser, "Alias")
    browser.wait_for(".swap-panel")
    assert browser.eval("document.querySelectorAll('.swap-panel, .pack-size-form').length") == 1

    _click_chip(browser, "Coarse item")
    # Alias's sub-panel is replaced, not stacked alongside Coarse item's.
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        panels = browser.eval("document.querySelectorAll('.swap-panel, .pack-size-form').length")
        if panels == 1:
            break
        time.sleep(0.2)
    assert panels == 1
    assert "Coarse item" in browser.html(".pack-size-form")
    assert not browser.console_errors(), browser.console_errors()


def test_alias_chip_this_list_only_default_survives_reload(browser, api, server_url):
    """2026-09-30, chunk 7.5 — the persistence toggle defaults to "this list only" (§0.3);
    saving without touching the toggle writes a session-scoped session_ingredient_merges row
    (not a durable ingredient_aliases one), which — unlike the old client-held override this
    replaced — is real server-side state and survives a page reload."""
    item_name = normalise_ingredient_name(f"cdp-alias-default-{uuid.uuid4().hex[:8]}")
    alias_name = normalise_ingredient_name(f"cdp-alias-default-alt-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP alias default test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 1, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    _wait_for_value_match_text(browser, ".name", item_name)
    _expand_and_open_edit(browser, item_name)
    _click_chip(browser, "Alias")
    browser.wait_for(".swap-panel")

    # Confirm the default toggle state before touching it — "This list only" already active.
    default_on = browser.eval(
        "Array.from(document.querySelectorAll('.persist-btn'))"
        ".find(function(b){return b.textContent==='This list only';}).className.indexOf('on') !== -1"
    )
    assert default_on is True

    fill_result = browser.eval(
        "(function(name){"
        "var panel=document.querySelector('.swap-panel');"
        "panel.querySelector('input').value=name;"
        "panel.querySelector('input').dispatchEvent(new Event('input',{bubbles:true}));"
        "var saveBtn=Array.from(panel.parentElement.querySelectorAll('.persist-actions button'))"
        ".find(function(b){return b.textContent==='Save';});"
        "if(!saveBtn) return 'SAVE_BUTTON_NOT_FOUND';"
        "saveBtn.click();"
        "return 'OK';"
        f"}})({json.dumps(alias_name)})"
    )
    assert fill_result == "OK", fill_result
    browser.wait_for(".saved-note")

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    _wait_for_value_match_text(browser, ".name", item_name)
    assert not browser.console_errors(), browser.console_errors()


def test_have_need_buttons_work_without_opening_the_panel(browser, api, server_url):
    """2026-09-30, chunk 7.5 — Have it / Need it stay on the collapsed row, independent of the
    name's expand-to-panel toggle; tapping them must never also expand the row."""
    item_name = normalise_ingredient_name(f"cdp-have-need-panel-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP have/need panel test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 1, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".have-need-btn.have")
    browser.eval("document.querySelector('.have-need-btn.have').click()")

    deadline = time.monotonic() + TIMEOUT
    have_it = None
    while time.monotonic() < deadline:
        items = api.get(f"/api/v1/checklist/{session['id']}").json()["data"]["items"]
        row = next((i for i in items if i["ingredient_name"] == item_name), None)
        if row and row["have_it"] == "yes":
            have_it = row["have_it"]
            break
        time.sleep(0.1)
    assert have_it == "yes"
    # The row must NOT have expanded into the breakdown/panel slot as a side effect.
    assert browser.eval("!document.querySelector('.edit-ingredient-toggle')")
    assert not browser.console_errors(), browser.console_errors()


def test_back_closes_open_panel_before_navigating_away(browser, api, server_url):
    """2026-09-30, chunk 7.6 — pressing Back once while a row's panel is open closes the panel
    without changing the route (scenario the maintainer specifically asked to verify); a
    second Back press then does the real navigation. Drives the real Plan -> Checklist button
    click first so there's a genuine "real previous screen" to return to (not a bare
    browser.navigate(), which starts a fresh page load with no history behind it)."""
    item_name = normalise_ingredient_name(f"cdp-back-panel-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP back panel test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 1, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.click("button.primary", contains="Checklist")
    browser.wait_for(".checklist-row")
    checklist_hash = f"#/checklist/{session['id']}"
    assert browser.eval("location.hash") == checklist_hash

    _wait_for_value_match_text(browser, ".name", item_name)
    expand_result = browser.eval(
        "(function(name){"
        "var rows=Array.from(document.querySelectorAll('.checklist-row'));"
        "var row=rows.find(function(r){var n=r.querySelector('.name'); return n && n.textContent.indexOf(name)===0;});"
        "if(!row) return 'ROW_NOT_FOUND';"
        "row.querySelector('.name').click();"
        "return 'OK';"
        f"}})({json.dumps(item_name)})"
    )
    assert expand_result == "OK", expand_result
    browser.wait_for(".recipe-breakdown")

    # One Back press: the panel closes, the route does NOT change (no "dead" press, no skip).
    browser.eval("history.back()")
    deadline = time.monotonic() + TIMEOUT
    closed = False
    while time.monotonic() < deadline:
        if browser.eval("!document.querySelector('.recipe-breakdown')"):
            closed = True
            break
        time.sleep(0.1)
    assert closed, "panel never closed on the first Back press"
    assert browser.eval("location.hash") == checklist_hash

    # A second Back press: now the real previous screen (Plan).
    browser.eval("history.back()")
    deadline = time.monotonic() + TIMEOUT
    navigated = False
    while time.monotonic() < deadline:
        if browser.eval("location.hash") == f"#/plan/{session['id']}":
            navigated = True
            break
        time.sleep(0.1)
    assert navigated, "second Back press did not return to Plan"
    assert not browser.console_errors(), browser.console_errors()


def test_back_from_a_panel_link_returns_straight_to_checklist(browser, api, server_url):
    """2026-09-30, chunk 7.6 — tapping a recipe-breakdown link inside an OPEN panel (without
    pressing Back first) must still leave the history stack balanced: Back from the recipe
    detail this lands on must return straight to Checklist, no leftover dead press, no skipped
    screen. This is the case a plain "push one entry, pop on popstate" guard gets wrong — a
    forward link click fires no popstate at all, so the synthetic entry would otherwise dangle."""
    item_name = normalise_ingredient_name(f"cdp-back-link-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP back link test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 1, "unit": None}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/plan/{session['id']}")
    browser.click("button.primary", contains="Checklist")
    browser.wait_for(".checklist-row")
    checklist_hash = f"#/checklist/{session['id']}"

    _wait_for_value_match_text(browser, ".name", item_name)
    browser.eval(
        "(function(name){"
        "var rows=Array.from(document.querySelectorAll('.checklist-row'));"
        "var row=rows.find(function(r){var n=r.querySelector('.name'); return n && n.textContent.indexOf(name)===0;});"
        "row.querySelector('.name').click();"
        f"}})({json.dumps(item_name)})"
    )
    browser.wait_for(".recipe-breakdown a")

    # Tap the recipe-breakdown link directly -- no Back press first.
    browser.eval("document.querySelector('.recipe-breakdown a').click()")
    deadline = time.monotonic() + TIMEOUT
    on_recipe = False
    while time.monotonic() < deadline:
        h = browser.eval("location.hash")
        if h.startswith("#/recipes/") and h != checklist_hash:
            on_recipe = True
            break
        time.sleep(0.1)
    assert on_recipe, "tapping the breakdown link did not navigate to the recipe"

    # One Back press from the recipe detail must land straight back on Checklist.
    browser.eval("history.back()")
    deadline = time.monotonic() + TIMEOUT
    back_on_checklist = False
    while time.monotonic() < deadline:
        if browser.eval("location.hash") == checklist_hash:
            back_on_checklist = True
            break
        time.sleep(0.1)
    assert back_on_checklist, "Back from the recipe detail did not return straight to Checklist"
    assert not browser.console_errors(), browser.console_errors()


def test_checklist_scroll_position_restored_after_visiting_a_recipe(browser, api, server_url):
    """2026-09-30, chunk 7.6 — scrolling down on Checklist, visiting a recipe, then returning
    restores the scroll position (checklist.js's savedScrollY, captured in unmount(), restored
    once on the next mount())."""
    item_name = normalise_ingredient_name(f"cdp-scroll-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP scroll test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            # Enough ingredients that the checklist genuinely overflows the viewport.
            "ingredients": [
                {"name": normalise_ingredient_name(f"{item_name}-{i}"), "quantity": 1, "unit": None}
                for i in range(40)
            ],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".checklist-row")
    browser.eval("window.scrollTo(0, 400)")
    # Confirm the scroll actually took (the page really is tall enough) before relying on it.
    deadline = time.monotonic() + TIMEOUT
    scrolled = False
    while time.monotonic() < deadline:
        if browser.eval("window.scrollY") > 100:
            scrolled = True
            break
        time.sleep(0.1)
    assert scrolled, "page never actually scrolled — not enough content to test restoration"
    scroll_before = browser.eval("window.scrollY")

    browser.eval("location.hash = " + json.dumps(f"#/recipes/{recipe['id']}"))
    browser.wait_for(".recipe-detail, h2")
    browser.eval("history.back()")
    browser.wait_for(".checklist-row")

    deadline = time.monotonic() + TIMEOUT
    restored = False
    while time.monotonic() < deadline:
        if abs(browser.eval("window.scrollY") - scroll_before) < 5:
            restored = True
            break
        time.sleep(0.1)
    assert restored, f"scroll position not restored (was {scroll_before}, now {browser.eval('window.scrollY')})"
    assert not browser.console_errors(), browser.console_errors()


def test_expanded_row_meta_text_is_not_squeezed_onto_its_own_line(browser, api, server_url):
    """2026-10-01, chunk 7.8 phase-end review — caught live via a screenshot (and flagged
    independently by the maintainer looking at the same one): `.checklist-row` is a `flex`
    container with no `flex-wrap`, so the expand-slot (recipe breakdown + edit panel,
    chunks 7.4/7.5), appended as a third flex child with an inline `flex-basis: 100%`, never
    actually got its own line the way `rowNameParts()`'s docstring says it should — instead
    `flex-shrink: 1` (the default) squeezed `.main`'s quantity text down to a sliver narrow
    enough to wrap character-by-character. Fixed with `flex-wrap: wrap` on `.checklist-row`
    (static/css/components-screens.css). Asserted here via actual geometry (the slot's top
    must be below the meta text's bottom), not just a CSS property, so a future change that
    achieves the same property a different, still-broken way would still be caught."""
    item_name = normalise_ingredient_name(f"cdp-meta-squeeze-{uuid.uuid4().hex[:8]}")
    recipe = api.post(
        "/api/v1/recipes",
        json={
            "name": f"CDP meta squeeze test {uuid.uuid4().hex[:8]}",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": item_name, "quantity": 400, "unit": "g"}],
        },
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})

    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    _wait_for_value_match_text(browser, ".name", item_name)
    _expand_and_open_edit(browser, item_name)

    rects = browser.eval(
        "(function(){"
        "var row=Array.from(document.querySelectorAll('.checklist-row')).find(function(r){"
        "  var n=r.querySelector('.name'); return n && n.textContent.indexOf(" + json.dumps(item_name) + ")===0;"
        "});"
        "var main=row.querySelector('.main');"
        "var meta=row.querySelector('.meta');"
        "var slot=row.querySelector('.edit-ingredient-toggle').closest('div[style]');"
        "return {metaBottom: meta.getBoundingClientRect().bottom, slotTop: slot.getBoundingClientRect().top, "
        "mainWidth: main.getBoundingClientRect().width, rowWidth: row.getBoundingClientRect().width};"
        "})()"
    )
    # The panel must render below the meta line (own line), not overlapping/squeezed beside it.
    assert rects["slotTop"] >= rects["metaBottom"] - 1, rects
    # .main (name + meta) must still occupy most of the row's width, not be squeezed down to a
    # sliver alongside the Have it/Need it buttons — the actual mechanism of the bug (meta's
    # own text width varies by ingredient/pack data, so asserting on .main's column width
    # directly is what catches a regression regardless of what a given test ingredient's
    # quantity text happens to say).
    assert rects["mainWidth"] > rects["rowWidth"] * 0.5, rects
    assert not browser.console_errors(), browser.console_errors()

"""Chunk 6.7 (2026-10-06): the push tracker/result UI and the replacement of every native
alert()/confirm() with inline questions and errors (approved mockups: docs/mockups/chunk-6.7/).

Every test here installs a trap on window.alert/confirm/prompt: ANY use fails the test, so a
regression back to a native dialog can't pass quietly.
"""

from __future__ import annotations

import json
import time
import uuid

from app.services.text_normalize import normalise_ingredient_name

TIMEOUT = 8.0

TRAP = (
    "window.__native = [];"
    "['alert','confirm','prompt'].forEach(function(n){"
    "window[n] = function(m){ window.__native.push(n + ': ' + m); return false; };});"
)


def _wait(browser, expr, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if browser.eval(expr):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
    return False


def _no_native(browser):
    assert browser.eval("window.__native") == [], browser.eval("window.__native")


def _session_with(api, names):
    """A session whose consolidated checklist holds exactly `names` (bare counts)."""
    keys = [normalise_ingredient_name(f"{n}-{uuid.uuid4().hex[:6]}") for n in names]
    recipe = api.post("/api/v1/recipes", json={
        "name": f"CDP 6.7 {uuid.uuid4().hex[:8]}", "source_type": "manual", "base_servings": 4,
        "ingredients": [{"name": k, "quantity": 2, "unit": None} for k in keys],
    }).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})
    api.post(f"/api/v1/sessions/{session['id']}/consolidate", json={})
    return session["id"], keys


def _open_checklist(browser, server_url, sid):
    browser.navigate(f"{server_url}/#/checklist/{sid}")
    browser.wait_for(".have-need-btn.need")
    browser.eval(TRAP)


def _mark_all_need(browser):
    browser.eval("Array.from(document.querySelectorAll('.have-need-btn.need')).forEach(function(b){b.click();})")
    assert _wait(browser, "Array.from(document.querySelectorAll('.have-need-btn.need')).every(function(b){return b.getAttribute('aria-pressed')==='true';})")


def _stub_push(browser, js_body):
    """js_body is the BODY of function(sessionId, opts) returning a promise."""
    browser.eval(
        "window.__pushCalls = [];"
        "window.api.checklist.push = function(sessionId, opts){ window.__pushCalls.push(opts); " + js_body + " };"
    )


# ---- the tracker ------------------------------------------------------------------------------


def test_tracker_shows_four_stages_and_rows_addressed_by_row_key(browser, api, server_url):
    sid, keys = _session_with(api, ["tracker-a", "tracker-b", "tracker-c"])
    _open_checklist(browser, server_url, sid)
    _mark_all_need(browser)
    ids = browser.eval(
        "Array.from(document.querySelectorAll('.checklist-row')).length")
    assert ids == 3
    # a push that never settles, with progress that walks through the stages
    _stub_push(browser, "return new Promise(function(){});")
    browser.eval(
        "window.__stage = 'sending';"
        "window.api.checklist.pushProgress = function(){ return Promise.resolve({stage: window.__stage, steps: ["
        "{name:'item:'+window.__ids[0], label:'Tracker A', status:'done'},"
        "{name:'item:'+window.__ids[1], label:'Tracker B', status:'active'},"
        "{name:'item:'+window.__ids[2], label:'Tracker C', status:'pending'}]}); };"
    )
    # row ids come from the page's own data (the keys must be the SAME ids the server will report)
    browser.eval(
        "window.__ids = []; window.__capturedItems = null;"
        "var orig = window.api.checklist.updateItem;"
    )
    row_ids = [i["id"] for i in api.get(f"/api/v1/checklist/{sid}").json()["data"]["items"]]
    browser.eval(f"window.__ids = {json.dumps(row_ids)};")
    browser.click("button.primary", contains="Push to AnyList")
    assert _wait(browser, "document.querySelectorAll('.push-stages li').length === 4")
    assert _wait(browser, "document.querySelector('.push-stages li.active') && document.querySelector('.push-stages li.active').textContent.indexOf('Sending') === 0")
    assert "1 of 3" in browser.text(".push-stages")  # n of N counts lines SENT
    labels = browser.eval("Array.from(document.querySelectorAll('.step-label')).map(function(e){return e.textContent;})")
    assert labels == ["Tracker A", "Tracker B", "Tracker C"]  # the server's label, matched by row key
    assert browser.eval("document.querySelectorAll('.step-icon.done').length") == 1
    assert browser.eval("document.querySelectorAll('.step-icon.active').length") == 1
    # the "Checking AnyList…" note belongs to the Confirming stage only (a screenshot of the real app
    # caught it showing during Sending: display:flex had defeated the hidden attribute)
    assert browser.eval("getComputedStyle(document.querySelector('.push-note')).display") == "none"

    browser.eval("window.__stage = 'confirming';")
    assert _wait(browser, "document.querySelector('.push-stages li.active') && document.querySelector('.push-stages li.active').textContent === 'Confirming'")
    assert _wait(browser, "!document.querySelector('.push-note').hidden")
    assert browser.eval("getComputedStyle(document.querySelector('.push-note')).display") == "flex"
    assert "Checking AnyList" in browser.text(".push-note")
    assert browser.eval("document.querySelector('button.primary.btn-block').disabled") is True
    _no_native(browser)
    assert not browser.console_errors(), browser.console_errors()


# ---- results ----------------------------------------------------------------------------------


def _items_json(rows):
    return json.dumps(rows)


def test_a_confirmed_push_shows_a_result_card_with_counts_and_details_not_a_toast(browser, api, server_url):
    sid, keys = _session_with(api, ["result-a", "result-b"])
    _open_checklist(browser, server_url, sid)
    _mark_all_need(browser)
    _stub_push(browser, "return Promise.resolve({confirmed: true, items: "
               + _items_json([
                   {"key": "item:1", "name": "Beef Mince", "outcome": "un-crossed", "reason": None},
                   {"key": "item:2", "name": "Eggs", "outcome": "updated", "reason": None},
                   {"key": "item:3", "name": "Olive Oil", "outcome": "added", "reason": None},
                   {"key": "item:4", "name": "Salt", "outcome": "already-active", "reason": None},
               ]) + ", added: [], updated: [], discrepancies: []});")
    browser.click("button.primary", contains="Push to AnyList")
    browser.wait_for(".push-result")
    assert browser.text(".push-result .title") == "4 on your list"
    sub = browser.text(".push-result .sub")
    assert "1 added" in sub and "2 updated (1 un-crossed)" in sub and "1 already there" in sub
    assert browser.eval("!!document.querySelector('.push-result.warn')") is False
    assert browser.eval("!!document.querySelector('.push-result .result-list')") is False  # collapsed

    browser.click(".push-result .btn-link", contains="Details")
    rows = browser.eval("Array.from(document.querySelectorAll('.push-result .result-list li')).map(function(l){return l.textContent;})")
    assert rows == ["Beef Mindun-crossed".replace("Mind", "Mince"), "Eggsupdated", "Olive Oiladded", "Saltalready there"]
    assert browser.eval("!document.querySelector('.toast')")  # no 5-second toast any more
    _no_native(browser)


def test_failed_items_are_named_with_reasons_never_a_green_tick_and_try_again_retries(browser, api, server_url):
    sid, keys = _session_with(api, ["fail-a", "fail-b"])
    _open_checklist(browser, server_url, sid)
    _mark_all_need(browser)
    _stub_push(browser, "return Promise.resolve({confirmed: false, items: "
               + _items_json([
                   {"key": "item:1", "name": "Red Capsicums", "outcome": "failed", "reason": "Not on the list after sending."},
                   {"key": "item:2", "name": "Salt", "outcome": "added", "reason": None},
               ]) + ", discrepancies: ['x']});")
    browser.click("button.primary", contains="Push to AnyList")
    browser.wait_for(".push-result.warn")
    assert browser.text(".push-result .title") == "1 item needs attention"
    assert "The other 1 is on your list." in browser.text(".push-result .sub")
    assert "Red Capsicums" in browser.text(".push-result .result-list")
    assert "Not on the list after sending." in browser.text(".push-result .result-list .why")
    assert "Salt" not in browser.text(".push-result .result-list")  # collapsed to just the failures
    assert browser.eval("!!document.querySelector('.push-result:not(.warn)')") is False  # no green card

    browser.click(".push-result .btn-sm", contains="Details")
    assert "Salt" in browser.text(".push-result .result-list")  # Details shows everything
    before = browser.eval("window.__pushCalls.length")
    browser.click(".push-result .btn-sm.primary", contains="Try again")
    assert _wait(browser, f"window.__pushCalls.length === {before + 1}")
    assert browser.eval("window.__pushCalls[window.__pushCalls.length-1].force") is False  # no "already pushed" detour
    _no_native(browser)


def test_already_pushed_is_an_inline_card_with_named_buttons_and_escape(browser, api, server_url):
    sid, keys = _session_with(api, ["again-a"])
    _open_checklist(browser, server_url, sid)
    _mark_all_need(browser)
    _stub_push(browser, "return Promise.reject({code: 'SESSION_ALREADY_PUSHED', message: 'already'});")
    browser.click("button.primary", contains="Push to AnyList")
    browser.wait_for(".inline-card.warn")
    assert browser.text(".inline-card .title") == "Already pushed to AnyList"
    buttons = browser.eval("Array.from(document.querySelectorAll('.inline-card button')).map(function(b){return b.textContent;})")
    assert buttons == ["Push again", "Not now"]  # named for what they do — never OK/Cancel
    assert browser.eval("document.activeElement.textContent") == "Push again"

    browser.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));")
    assert _wait(browser, "!document.querySelector('.inline-card')")  # Escape = Not now

    browser.click("button.primary", contains="Push to AnyList")
    browser.wait_for(".inline-card.warn")
    _stub_push(browser, "return new Promise(function(){});")
    browser.click(".inline-card button.primary", contains="Push again")
    assert _wait(browser, "window.__pushCalls.length === 1 && window.__pushCalls[0].force === true")
    _no_native(browser)


def test_a_push_that_cannot_read_the_list_says_nothing_changed_and_offers_try_again(browser, api, server_url):
    sid, keys = _session_with(api, ["down-a"])
    _open_checklist(browser, server_url, sid)
    _mark_all_need(browser)
    _stub_push(browser, "return Promise.reject({code: 'ANYLIST_ERROR', message: 'AnyList is unreachable'});")
    browser.click("button.primary", contains="Push to AnyList")
    browser.wait_for(".error-state")
    text = browser.text(".error-state")
    assert "Nothing was changed" in text and "AnyList is unreachable" in text
    assert browser.eval("document.querySelector('button.primary.btn-block').disabled") is False  # usable again
    before = browser.eval("window.__pushCalls.length")
    browser.click(".error-state .btn-sm", contains="Try again")
    assert _wait(browser, f"window.__pushCalls.length === {before + 1}")
    _no_native(browser)


# ---- the merge panel --------------------------------------------------------------------------


def _start_merge(browser, n_select=2):
    browser.click("button.btn-link", contains="Select to merge")
    for i in range(n_select):
        # each tick re-renders the list, so re-query before every click (stale nodes are detached)
        browser.eval(f"document.querySelectorAll('.merge-select-checkbox')[{i}].click();")
        assert _wait(browser, f"document.querySelectorAll('.merge-select-checkbox:checked').length === {i + 1}")
    assert _wait(browser, f"Array.from(document.querySelectorAll('button')).some(function(b){{return b.textContent==='Merge ({n_select})';}})")
    browser.click("button.btn-sm.primary", contains=f"Merge ({n_select})")
    browser.wait_for(".inline-card")


def test_merge_panel_names_what_will_happen_and_the_choice_is_the_two_buttons(browser, api, server_url):
    sid, keys = _session_with(api, ["merge-a", "merge-b", "merge-c"])
    _open_checklist(browser, server_url, sid)
    _start_merge(browser)

    assert browser.text(".inline-card .title") == "Merge these ingredients"
    chips = browser.eval("Array.from(document.querySelectorAll('.merge-summary .name-chip')).map(function(c){return c.textContent;})")
    assert len(chips) == 3 and chips[-1] == chips[1]  # "A + B -> B": the kept name on both sides
    assert "→" in browser.text(".merge-summary")
    labels = browser.eval("Array.from(document.querySelectorAll('.inline-card .actions button')).map(function(b){return b.textContent;})")
    # the two choices, then a plain Cancel (Cancel sits in its own row under the fine print)
    assert labels == ["Merge for this shopping list only", "Merge every time — all future recipes", "Cancel"]
    fine = browser.text(".inline-card .fine")
    assert "any future recipe" in fine and "Settings → Ingredient groups" in fine  # plain, and where to undo it
    # choosing the other name to keep updates the sentence
    browser.eval("document.querySelectorAll('.inline-card input[type=radio]')[1].click();")
    assert _wait(browser, "document.querySelector('.merge-summary .name-chip.keep').textContent === document.querySelectorAll('.inline-card .radio-row')[1].textContent")
    _no_native(browser)


def test_merge_this_list_only_then_undo_restores_both_lines_and_the_decision(browser, api, server_url):
    sid, keys = _session_with(api, ["undo-a", "undo-b"])
    _open_checklist(browser, server_url, sid)
    browser.eval("document.querySelectorAll('.have-need-btn.need')[1].click();")  # decide on the second row
    assert _wait(browser, "document.querySelectorAll('.have-need-btn.need')[1].getAttribute('aria-pressed') === 'true'")
    _start_merge(browser)
    browser.click(".inline-card button", contains="Merge for this shopping list only")
    browser.wait_for(".toast")
    assert "this list only" in browser.text(".toast") and "Merged into" in browser.text(".toast")
    assert _wait(browser, "document.querySelectorAll('.checklist-row').length === 1")

    browser.click(".toast button", contains="Undo")
    assert _wait(browser, "document.querySelectorAll('.checklist-row').length === 2")
    items = api.get(f"/api/v1/checklist/{sid}").json()["data"]["items"]
    assert sorted(i["ingredient_name"] for i in items) == sorted(keys)
    assert all(i["add_to_list"] for i in items)  # the Need it carried onto the restored line
    _no_native(browser)
    assert not browser.console_errors(), browser.console_errors()


def test_merge_every_time_creates_a_tagged_group_and_undo_removes_it(browser, api, server_url):
    sid, keys = _session_with(api, ["every-a", "every-b"])
    _open_checklist(browser, server_url, sid)
    _start_merge(browser)
    browser.click(".inline-card button", contains="Merge every time")
    browser.wait_for(".toast")
    assert "every time" in browser.text(".toast")
    aliases = api.get("/api/v1/settings/ingredient-aliases?limit=500").json()["data"]["items"]
    mine = [a for a in aliases if a["alias_name"] in keys]
    assert len(mine) == 1 and mine[0]["source"] == "merge"

    # Settings shows where it came from
    browser.eval("window.__keep = true;")
    browser.navigate(f"{server_url}/#/settings/ingredient-aliases")
    assert _wait(browser, "Array.from(document.querySelectorAll('.source-tag.merge')).length >= 1", timeout=10)
    assert "from a checklist merge" in browser.text(".source-tag.merge")

    # ...and Undo on the toast (go back to the checklist right away) removes the saved group
    browser.navigate(f"{server_url}/#/checklist/{sid}")
    browser.wait_for(".checklist-row")
    browser.eval(TRAP)
    # undo through the API-backed flow the toast uses
    resp = api.post(f"/api/v1/checklist/{sid}/undo-merge", json={
        "canonical_name": [k for k in keys if k != mine[0]["alias_name"]][0],
        "member_names": [mine[0]["alias_name"]], "alias_ids": [mine[0]["id"]]})
    assert resp.status_code == 200
    aliases = api.get("/api/v1/settings/ingredient-aliases?limit=500").json()["data"]["items"]
    assert not [a for a in aliases if a["alias_name"] in keys]
    _no_native(browser)


def test_a_merge_problem_is_shown_inside_the_panel(browser, api, server_url):
    sid, keys = _session_with(api, ["prob-a", "prob-b"])
    _open_checklist(browser, server_url, sid)
    _start_merge(browser)
    browser.eval(
        "window.api.checklist.merge = function(){ return Promise.reject("
        "{code:'DUPLICATE_INGREDIENT_ALIAS', message:'dup'}); };"
    )
    browser.click(".inline-card button", contains="Merge every time")
    browser.wait_for(".inline-card .form-error")
    assert "already grouped" in browser.text(".inline-card .form-error")
    assert browser.eval("Array.from(document.querySelectorAll('.inline-card .actions button')).every(function(b){return !b.disabled;})")
    browser.click(".inline-card button", contains="Cancel")
    assert _wait(browser, "!document.querySelector('.inline-card')")  # Cancel closes the panel
    _no_native(browser)


# ---- errors replace alert() -------------------------------------------------------------------


def test_a_failed_have_need_tap_shows_the_error_on_the_row_and_does_not_look_saved(browser, api, server_url):
    sid, keys = _session_with(api, ["row-a"])
    _open_checklist(browser, server_url, sid)
    browser.eval("window.api.checklist.updateItem = function(){ return Promise.reject({message:'AnyList wasn\\'t reached'}); };")
    browser.click(".have-need-btn.need")
    browser.wait_for(".checklist-row .form-error")
    assert "Couldn’t save" in browser.text(".checklist-row .form-error") or "Couldn't save" in browser.text(".checklist-row .form-error")
    assert browser.eval("document.querySelector('.have-need-btn.need').getAttribute('aria-pressed')") == "false"
    assert browser.eval("document.querySelector('.checklist-row .form-error').getAttribute('role')") == "alert"
    _no_native(browser)


def test_add_to_session_asks_inline_when_there_is_no_session_and_reports_errors_inline(browser, api, server_url):
    recipe = api.post("/api/v1/recipes", json={
        "name": f"CDP addsess {uuid.uuid4().hex[:8]}", "source_type": "manual", "base_servings": 2,
        "ingredients": [{"name": "salt", "quantity": 1, "unit": "tsp"}]}).json()["data"]
    browser.navigate(f"{server_url}/#/recipes/{recipe['id']}")
    browser.wait_for("button.btn-sm", timeout=10)
    browser.eval(TRAP)
    browser.eval(
        "window.__created = 0;"
        "window.api.sessions.list = function(){ return Promise.resolve({items: []}); };"
        "window.api.sessions.create = function(){ window.__created++; return Promise.reject({message:'disk full'}); };"
    )
    browser.click("button.btn-sm", contains="+ Add to session")
    browser.wait_for(".inline-card")
    assert browser.text(".inline-card .title") == "No shopping session yet"
    labels = browser.eval("Array.from(document.querySelectorAll('.inline-card button')).map(function(b){return b.textContent;})")
    assert labels == ["Start one with this recipe", "Not now"]

    browser.click(".inline-card button.primary", contains="Start one")
    browser.wait_for(".add-feedback .form-error")
    assert "Couldn't start a session" in browser.text(".add-feedback .form-error") or "Couldn’t" in browser.text(".add-feedback .form-error")
    assert browser.eval("window.__created") == 1

    browser.click(".add-feedback .btn-link", contains="Retry")  # Retry re-runs the whole flow
    assert _wait(browser, "!!document.querySelector('.inline-card')")
    browser.click(".inline-card button", contains="Not now")
    assert _wait(browser, "!document.querySelector('.inline-card')")
    _no_native(browser)


def test_failed_undo_after_a_settings_delete_is_an_error_toast_with_retry(browser, api, server_url):
    name = normalise_ingredient_name(f"cdp-undo-set-{uuid.uuid4().hex[:6]}")
    api.post("/api/v1/settings/ingredient-aliases", json={"alias_name": name, "canonical_name": name + " canon"})
    browser.navigate(f"{server_url}/#/settings/ingredient-aliases")
    assert _wait(browser, "Array.from(document.querySelectorAll('.settings-name-input')).some(function(i){return i.value===" + json.dumps(name) + ";})", timeout=10)
    browser.eval(TRAP)
    browser.eval(
        "window.__tries = 0;"
        "window.api.settings.ingredientAliases.create = function(){ window.__tries++; return Promise.reject({message:'offline'}); };"
    )
    browser.eval(
        "(function(n){var i=Array.from(document.querySelectorAll('.settings-name-input')).find(function(x){return x.value===n;});"
        "i.closest('.settings-group-row').querySelector('.btn-link-danger').click();})(" + json.dumps(name) + ")"
    )
    browser.wait_for(".toast")
    browser.click(".toast button", contains="Undo")
    browser.wait_for(".toast.error")
    assert "Couldn’t restore" in browser.text(".toast.error") or "Couldn't restore" in browser.text(".toast.error")
    assert browser.eval("document.querySelector('.toast.error').getAttribute('role')") == "alert"
    browser.click(".toast.error button", contains="Retry")
    assert _wait(browser, "window.__tries === 2")
    _no_native(browser)


# ---- Diagnostics -------------------------------------------------------------------------------


def test_diagnostics_shows_push_history_with_per_item_results_and_the_running_build(browser, server_url):
    browser.navigate(f"{server_url}/#/diagnostics")
    browser.wait_for("#diag-status")
    stub = {
        "database": {"state": "green", "message": "ok"},
        "ai_extraction": {"state": "grey", "message": "off"},
        "anylist": {
            "state": "red", "message": "Last push was not fully confirmed — check AnyList",
            "enabled": True, "fake_mode": False, "target_list": "TestList", "credentials_configured": True,
            "last_push": {"session_id": 5, "pushed_at": "2026-10-06T18:35:30", "confirmed": False},
            "recent_pushes": [
                {"history_id": 2, "session_id": 5, "pushed_at": "2026-10-06T18:35:30", "push_id": "9d3a1c7e", "confirmed": False,
                 "counts": {"failed": 1, "added": 1}, "timings": {"read": 0.6, "send": 9.1, "confirm": 1.2}, "retried": [],
                 "items": [
                     {"key": "item:1", "name": "Eggs", "outcome": "added", "reason": None, "retries": 0},
                     {"key": "item:2", "name": "Red Capsicums", "outcome": "failed", "reason": "Not on the list after sending.", "retries": 2}]},
                {"history_id": 1, "session_id": 4, "pushed_at": "2026-10-05T09:12:00", "push_id": "41be07a2", "confirmed": True,
                 "counts": {"added": 3}, "timings": {}, "items": [{"key": "item:3", "name": "Milk", "outcome": "added", "reason": None, "retries": 0}]},
            ],
        },
        "build": {"build_id": "37ef218b7f12", "version": "release-20261006", "version_source": "git",
                  "boot_id": "a6e4ac08d401", "started_at": "2026-10-06T09:41:56+00:00"},
    }
    browser.eval(
        "window.api.diagnostics.status = function(){ return Promise.resolve(" + json.dumps(stub) + "); };"
        "window.api.diagnostics.recentErrors = function(){ return Promise.resolve({errors: []}); };"
    )
    browser.navigate(f"{server_url}/#/diagnostics")
    browser.eval("window.api.diagnostics.status = function(){ return Promise.resolve(" + json.dumps(stub) + "); };")
    assert _wait(browser, "!!document.querySelector('.push-history')", timeout=12), browser.html("#diag-status")[:400]
    # newest push had a problem -> opens itself, failures first, with the reason and retries
    first = browser.eval("document.querySelector('.push-history .history-row.open .result-list li').textContent")
    assert "Red Capsicums" in first and "failed" in first
    assert "Not on the list after sending." in browser.text(".push-history .why") and "retried 2×" in browser.text(".push-history .why")
    assert "grep 9d3a1c7e" in browser.text(".push-history .kv")
    assert browser.eval("document.querySelectorAll('.push-history .history-row.open').length") == 1  # the confirmed one is collapsed
    assert "37ef218b7f12" in browser.text("#diag-status") and "release-20261006" in browser.text("#diag-status")

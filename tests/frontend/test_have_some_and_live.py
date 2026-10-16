"""Checklist "I have some" and live updates between phones (Chunk 6.7, polish batch 3)."""

from __future__ import annotations

import time
import uuid

from app.services.text_normalize import normalise_ingredient_name

TIMEOUT = 10.0


def _wait(browser, expr: str, timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.eval(expr):
            return True
        time.sleep(0.1)
    return False


def _plan(api, name: str, quantity: float, unit=None) -> dict:
    recipe = api.post(
        "/api/v1/recipes",
        json={"name": f"CDP have some {uuid.uuid4().hex[:8]}", "source_type": "manual", "base_servings": 4,
              "ingredients": [{"name": name, "quantity": quantity, "unit": unit}]},
    ).json()["data"]
    session = api.post("/api/v1/sessions", json={}).json()["data"]
    api.post(f"/api/v1/sessions/{session['id']}/recipes", json={"recipe_id": recipe["id"]})
    return session


def test_i_have_some_is_on_the_row_and_reduces_what_is_bought(browser, api, server_url):
    name = normalise_ingredient_name(f"cdp-tomato-{uuid.uuid4().hex[:8]}")
    session = _plan(api, name, 3)
    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".have-link")  # no panel to open first
    browser.click(".have-link")
    browser.wait_for(".have-inline input")
    browser.fill(".have-inline input", "1")
    browser.click(".have-inline button", contains="Save")
    assert _wait(browser, "document.querySelector('.checklist-row .meta').textContent.indexOf('Buy 2 · have 1 of 3') >= 0"), \
        browser.text(".checklist-row .meta")
    assert browser.text(".have-link") == "Change what I have"
    row = next(i for i in api.get(f"/api/v1/checklist/{session['id']}").json()["data"]["items"] if i["ingredient_name"] == name)
    assert row["total_quantity"] == 3 and row["have_quantity"] == 1 and row["buy_quantity"] == 2
    assert not browser.console_errors(), browser.console_errors()


def test_an_open_have_some_field_survives_a_rerender_and_having_it_all_means_have_it(browser, api, server_url):
    name = normalise_ingredient_name(f"cdp-lime-{uuid.uuid4().hex[:8]}")
    session = _plan(api, name, 3)
    browser.navigate(f"{server_url}/#/checklist/{session['id']}")
    browser.wait_for(".have-link")
    browser.click(".have-link")
    browser.fill(".have-inline input", "3")
    # an unrelated re-render (expanding the row's panel) must not lose the typed text
    browser.click(".recipe-row-name-btn")
    assert _wait(browser, "document.querySelector('.have-inline input') && document.querySelector('.have-inline input').value === '3'")
    browser.click(".have-inline button", contains="Save")
    assert _wait(browser, "document.querySelector('.have-need-btn.have').getAttribute('aria-pressed') === 'true'")
    row = next(i for i in api.get(f"/api/v1/checklist/{session['id']}").json()["data"]["items"] if i["ingredient_name"] == name)
    assert row["have_it"] == "yes" and row["add_to_list"] is False

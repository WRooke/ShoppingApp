"""Smoke tests for /api/v1/recipes — happy path + one error path per feature,
per CLAUDE.md > Code Architecture & Maintainability. Deeper CRUD/edge-case
coverage lives in tests/services/test_recipes.py; these just prove the HTTP
layer (routing, envelope, status codes, 404 translation) is wired up right.
"""

from __future__ import annotations


def _create_recipe(client, **overrides):
    payload = {
        "name": "Spaghetti Bolognese",
        "source_type": "manual",
        "base_servings": 4,
        "ingredients": [{"name": "Beef Mince", "quantity": 500, "unit": "g"}],
        # conftest shares one DB across the session, so repeat creates would trip the
        # Phase 4 duplicate check — these smoke tests aren't about that (there's a
        # dedicated test below), so opt out by default.
        "allow_duplicate": True,
    }
    payload.update(overrides)
    return client.post("/api/v1/recipes", json=payload)


def test_create_recipe_happy_path(client):
    resp = _create_recipe(client)

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "Spaghetti Bolognese"
    assert body["data"]["ingredients"][0]["name"] == "beef mince"  # normalised


def test_create_recipe_rejects_missing_name(client):
    resp = client.post("/api/v1/recipes", json={"source_type": "manual"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_list_recipes_happy_path(client):
    # conftest.py shares one SQLite file across the whole test session, so other
    # tests' recipes are already in this table — assert on presence, not totals.
    alpha = _create_recipe(client, name="ZZ-Alpha-List-Test").json()["data"]
    bravo = _create_recipe(client, name="ZZ-Bravo-List-Test").json()["data"]

    resp = client.get("/api/v1/recipes?limit=200")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    ids = {r["id"] for r in body["data"]["items"]}
    assert {alpha["id"], bravo["id"]} <= ids


def test_list_recipes_search_filters_by_name(client):
    _create_recipe(client, name="Chicken Curry")
    _create_recipe(client, name="Beef Tacos")

    resp = client.get("/api/v1/recipes?search=curry")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "Chicken Curry"


def test_get_recipe_happy_path(client):
    created = _create_recipe(client).json()["data"]

    resp = client.get(f"/api/v1/recipes/{created['id']}")

    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == created["id"]


def test_get_recipe_not_found_returns_structured_404(client):
    resp = client.get("/api/v1/recipes/999999")

    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "RECIPE_NOT_FOUND"


def test_update_recipe_happy_path(client):
    created = _create_recipe(client).json()["data"]

    resp = client.patch(f"/api/v1/recipes/{created['id']}", json={"rating": "up"})

    assert resp.status_code == 200
    assert resp.json()["data"]["rating"] == "up"


def test_update_recipe_not_found_returns_structured_404(client):
    resp = client.patch("/api/v1/recipes/999999", json={"rating": "up"})

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RECIPE_NOT_FOUND"


def test_source_provenance_round_trips_through_create_and_get(client):
    created = _create_recipe(
        client, name="ZZ-Provenance-Test", source_book="Ottolenghi SIMPLE", source_page="142-143"
    ).json()["data"]
    assert created["source_book"] == "Ottolenghi SIMPLE"
    assert created["source_page"] == "142-143"

    fetched = client.get(f"/api/v1/recipes/{created['id']}").json()["data"]
    assert fetched["source_book"] == "Ottolenghi SIMPLE"
    assert fetched["source_page"] == "142-143"


def test_update_recipe_sets_source_page(client):
    created = _create_recipe(client, name="ZZ-Provenance-Patch-Test").json()["data"]

    resp = client.patch(f"/api/v1/recipes/{created['id']}", json={"source_page": "ch. 3"})

    assert resp.status_code == 200
    assert resp.json()["data"]["source_page"] == "ch. 3"


def test_create_recipe_rejects_overlong_source_page(client):
    resp = _create_recipe(client, name="ZZ-Provenance-TooLong", source_page="x" * 51)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_archive_recipe_removes_it_from_default_list(client):
    created = _create_recipe(client, name="ZZ-Archive-Test").json()["data"]

    del_resp = client.delete(f"/api/v1/recipes/{created['id']}")
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["archived"] is True

    # Scope by search rather than raw total — the test DB is shared across the session.
    list_resp = client.get("/api/v1/recipes?search=ZZ-Archive-Test")
    assert list_resp.json()["data"]["total"] == 0

    list_resp_all = client.get("/api/v1/recipes?search=ZZ-Archive-Test&include_archived=true")
    assert list_resp_all.json()["data"]["total"] == 1


def test_add_ingredient_happy_path(client):
    created = _create_recipe(client).json()["data"]

    resp = client.post(
        f"/api/v1/recipes/{created['id']}/ingredients",
        json={"name": "  Spring Onion ", "quantity": 2},
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["name"] == "spring onion"


def test_add_ingredient_recipe_not_found_returns_structured_404(client):
    resp = client.post(
        "/api/v1/recipes/999999/ingredients", json={"name": "salt", "quantity": 1}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RECIPE_NOT_FOUND"


def test_update_ingredient_happy_path(client):
    created = _create_recipe(client).json()["data"]
    ingredient_id = created["ingredients"][0]["id"]

    resp = client.patch(
        f"/api/v1/recipes/{created['id']}/ingredients/{ingredient_id}",
        json={"quantity": 750},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["quantity"] == 750


def test_update_ingredient_not_found_returns_structured_404(client):
    created = _create_recipe(client).json()["data"]

    resp = client.patch(
        f"/api/v1/recipes/{created['id']}/ingredients/999999", json={"quantity": 1}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INGREDIENT_NOT_FOUND"


def test_delete_ingredient_happy_path(client):
    created = _create_recipe(client).json()["data"]
    ingredient_id = created["ingredients"][0]["id"]

    resp = client.delete(f"/api/v1/recipes/{created['id']}/ingredients/{ingredient_id}")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_delete_ingredient_not_found_returns_structured_404(client):
    created = _create_recipe(client).json()["data"]

    resp = client.delete(f"/api/v1/recipes/{created['id']}/ingredients/999999")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INGREDIENT_NOT_FOUND"


# --- duplicate recipe prevention (Phase 4 — CLAUDE.md > Duplicate Recipe Prevention) -----


def test_create_recipe_possible_duplicate_returns_structured_409(client):
    _create_recipe(client, name="ZZ-Dup-Router-Test")

    resp = client.post(
        "/api/v1/recipes",
        json={
            "name": "zz-dup-router-test",
            "source_type": "manual",
            "ingredients": [{"name": "salt", "quantity": 1}],
        },
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "POSSIBLE_DUPLICATE_RECIPE"
    assert body["error"]["detail"][0]["matched_signal"] == "name_exact"
    assert body["error"]["detail"][0]["archived"] is False


def test_create_recipe_allow_duplicate_true_saves_anyway(client):
    _create_recipe(client, name="ZZ-Allow-Dup-Router-Test")

    resp = client.post(
        "/api/v1/recipes",
        json={
            "name": "ZZ-Allow-Dup-Router-Test",
            "source_type": "manual",
            "ingredients": [{"name": "salt", "quantity": 1}],
            "allow_duplicate": True,
        },
    )

    assert resp.status_code == 201


def test_check_duplicate_endpoint_reports_matches(client):
    created = _create_recipe(client, name="ZZ-CheckDup-Endpoint-Test").json()["data"]

    resp = client.get("/api/v1/recipes/check-duplicate?name=zz-checkdup-endpoint-test")

    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()["data"]["matches"]}
    assert created["id"] in ids


def test_check_duplicate_endpoint_excludes_self(client):
    created = _create_recipe(client, name="ZZ-CheckDup-ExcludeSelf-Test").json()["data"]

    resp = client.get(
        f"/api/v1/recipes/check-duplicate?name=ZZ-CheckDup-ExcludeSelf-Test&exclude_id={created['id']}"
    )

    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()["data"]["matches"]}
    assert created["id"] not in ids


def test_restore_recipe_clears_archived(client):
    created = _create_recipe(client, name="ZZ-Restore-Router-Test").json()["data"]
    client.delete(f"/api/v1/recipes/{created['id']}")

    resp = client.post(f"/api/v1/recipes/{created['id']}/restore")

    assert resp.status_code == 200
    assert resp.json()["data"]["archived_at"] is None


def test_capture_url_short_circuits_on_existing_source_url(client):
    # An exact source_url match returns 409 BEFORE any Claude call — no fake-mode / httpx
    # mock needed here precisely because the extraction never runs.
    client.post(
        "/api/v1/recipes",
        json={
            "name": "ZZ-URL-ShortCircuit-Test",
            "source_type": "url",
            "source_url": "https://example.com/zz-shortcircuit",
            "ingredients": [{"name": "salt", "quantity": 1}],
            "allow_duplicate": True,
        },
    )

    resp = client.post(
        "/api/v1/recipes/capture/url",
        json={"url": "https://example.com/zz-shortcircuit?utm_campaign=x"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "POSSIBLE_DUPLICATE_RECIPE"
    assert resp.json()["error"]["detail"][0]["matched_signal"] == "source_url"

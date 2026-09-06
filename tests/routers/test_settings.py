"""Smoke tests for /api/v1/settings — happy path + one error path per
feature, per CLAUDE.md > Code Architecture & Maintainability. Deeper
CRUD/edge-case coverage lives in tests/services/test_settings.py; these just
prove the HTTP layer (routing, envelope, status codes, 404/409 translation)
is wired up right.
"""

from __future__ import annotations


# --- staples ---------------------------------------------------------------


def test_create_staple_happy_path(client):
    # conftest.py shares one SQLite file across the whole test session, and
    # seed_reference_data() has already inserted the real staple starter list
    # into it — use a name that can't collide with those (see
    # test_list_recipes_happy_path in test_recipes.py for the same pattern).
    resp = client.post("/api/v1/settings/staples", json={"name": "  ZZ-Happy-Staple  "})

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "zz-happy-staple"  # normalised


def test_create_staple_rejects_missing_name(client):
    resp = client.post("/api/v1/settings/staples", json={})

    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_create_staple_duplicate_name_returns_structured_409(client):
    client.post("/api/v1/settings/staples", json={"name": "ZZ-Dup-Staple"})

    resp = client.post("/api/v1/settings/staples", json={"name": "ZZ-Dup-Staple"})

    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DUPLICATE_STAPLE_NAME"


def test_list_staples_happy_path(client):
    created = client.post("/api/v1/settings/staples", json={"name": "ZZ-List-Staple"}).json()[
        "data"
    ]

    resp = client.get("/api/v1/settings/staples")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    ids = {s["id"] for s in body["data"]["items"]}
    assert created["id"] in ids


def test_update_staple_happy_path(client):
    created = client.post("/api/v1/settings/staples", json={"name": "ZZ-Update-Staple"}).json()[
        "data"
    ]

    resp = client.patch(
        f"/api/v1/settings/staples/{created['id']}", json={"notes": "test note"}
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["notes"] == "test note"


def test_update_staple_not_found_returns_structured_404(client):
    resp = client.patch("/api/v1/settings/staples/999999", json={"notes": "x"})

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STAPLE_NOT_FOUND"


def test_delete_staple_happy_path(client):
    created = client.post("/api/v1/settings/staples", json={"name": "ZZ-Delete-Staple"}).json()[
        "data"
    ]

    resp = client.delete(f"/api/v1/settings/staples/{created['id']}")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_delete_staple_not_found_returns_structured_404(client):
    resp = client.delete("/api/v1/settings/staples/999999")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STAPLE_NOT_FOUND"


# --- product_units -----------------------------------------------------


def _create_product_unit(client, **overrides):
    payload = {
        "ingredient_name": "ZZ-Test-Ingredient",
        "purchase_label": "500g pack",
        "purchase_qty": 500,
        "purchase_unit": "g",
    }
    payload.update(overrides)
    return client.post("/api/v1/settings/product-units", json=payload)


def test_create_product_unit_happy_path(client):
    resp = _create_product_unit(client)

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["ingredient_name"] == "zz-test-ingredient"  # normalised
    assert body["data"]["is_preseeded"] is False


def test_create_product_unit_rejects_non_positive_qty(client):
    resp = _create_product_unit(client, purchase_qty=0)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_product_unit_duplicate_ingredient_name_returns_structured_409(client):
    _create_product_unit(client, ingredient_name="ZZ-Dup-Ingredient")

    resp = _create_product_unit(client, ingredient_name="ZZ-Dup-Ingredient")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_PRODUCT_UNIT_NAME"


def test_list_product_units_happy_path(client):
    created = _create_product_unit(client, ingredient_name="ZZ-List-Ingredient").json()["data"]

    resp = client.get("/api/v1/settings/product-units")

    assert resp.status_code == 200
    body = resp.json()
    ids = {u["id"] for u in body["data"]["items"]}
    assert created["id"] in ids


def test_update_product_unit_happy_path(client):
    created = _create_product_unit(client, ingredient_name="ZZ-Update-Ingredient").json()["data"]

    resp = client.patch(
        f"/api/v1/settings/product-units/{created['id']}", json={"purchase_qty": 1000}
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["purchase_qty"] == 1000


def test_update_product_unit_not_found_returns_structured_404(client):
    resp = client.patch(
        "/api/v1/settings/product-units/999999", json={"purchase_qty": 1}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_UNIT_NOT_FOUND"


def test_delete_product_unit_happy_path(client):
    created = _create_product_unit(client, ingredient_name="ZZ-Delete-Ingredient").json()["data"]

    resp = client.delete(f"/api/v1/settings/product-units/{created['id']}")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_delete_product_unit_not_found_returns_structured_404(client):
    resp = client.delete("/api/v1/settings/product-units/999999")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_UNIT_NOT_FOUND"


def test_section_vocabulary_returns_ok_envelope(client):
    resp = client.get("/api/v1/settings/section-vocabulary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "produce" in body["data"]["sections"]
    assert "other" in body["data"]["sections"]


# --- remembered substitutions: quick-pick library (Phase 3.9 M4) -----------------------


def _create_sub(client, original, substitute, **extra):
    payload = {"original_name": original, "substitute_name": substitute}
    payload.update(extra)
    return client.post("/api/v1/settings/substitutions", json=payload)


def test_create_substitution_normalises_and_no_default_concept(client):
    resp = _create_sub(client, "ZZ-Bulgarian Feta", "ZZ-Regular Feta", note="close enough")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["original_name"] == "zz-bulgarian feta"  # normalised
    assert body["note"] == "close enough"
    assert "is_default" not in body


def test_create_substitution_duplicate_returns_structured_409(client):
    _create_sub(client, "ZZ-Dup-Orig", "ZZ-Dup-Sub")
    resp = _create_sub(client, "zz-dup-orig", "zz-dup-sub")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_SUBSTITUTION"


def test_create_self_substitution_returns_structured_422(client):
    resp = _create_sub(client, "ZZ-Self", "zz-self")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SUBSTITUTION"


def test_multiple_substitutes_per_original_and_patch_note(client):
    a = _create_sub(client, "ZZ-Multi", "ZZ-Sub-A").json()["data"]
    b = _create_sub(client, "ZZ-Multi", "ZZ-Sub-B").json()["data"]
    assert a["id"] != b["id"]

    resp = client.patch(
        f"/api/v1/settings/substitutions/{b['id']}", json={"note": "use this in a pinch"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["note"] == "use this in a pinch"

    listed = client.get("/api/v1/settings/substitutions?limit=500").json()["data"]["items"]
    mine = [r for r in listed if r["original_name"] == "zz-multi"]
    assert {r["substitute_name"] for r in mine} == {"zz-sub-a", "zz-sub-b"}


def test_delete_substitution(client):
    row = _create_sub(client, "ZZ-DeleteMe", "ZZ-DeleteMe-Sub").json()["data"]
    resp = client.delete(f"/api/v1/settings/substitutions/{row['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_update_substitution_not_found_returns_structured_404(client):
    resp = client.patch(
        "/api/v1/settings/substitutions/999999", json={"substitute_name": "x"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUBSTITUTION_NOT_FOUND"

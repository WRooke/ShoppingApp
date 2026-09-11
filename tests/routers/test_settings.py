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


def test_create_substitution_with_m8_equivalence_pair(client):
    resp = _create_sub(
        client, "ZZ-Corn-Cobs", "ZZ-Canned-Corn",
        original_qty=2, original_unit="Cob", substitute_qty=2, substitute_unit="CAN",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["original_qty"] == 2 and body["original_unit"] == "cob"
    assert body["substitute_qty"] == 2 and body["substitute_unit"] == "can"


def test_create_substitution_half_equivalence_pair_returns_422(client):
    resp = _create_sub(
        client, "ZZ-Half-Pair", "ZZ-Half-Sub", original_qty=2, original_unit="cob"
    )
    assert resp.status_code == 422


# --- "the usuals" (Phase 5 Chunk 5.4) --------------------------------------------------


def test_usuals_crud_roundtrip(client):
    created = client.post(
        "/api/v1/settings/usuals",
        json={"name": "ZZ Laundry Powder", "cadence_days": 21, "notes": "big box"},
    )
    assert created.status_code == 201
    body = created.json()["data"]
    assert body["name"] == "zz laundry powder"
    assert body["cadence_days"] == 21
    assert body["is_due"] is True  # never added

    uid = body["id"]
    patched = client.patch(f"/api/v1/settings/usuals/{uid}", json={"cadence_days": 30})
    assert patched.status_code == 200 and patched.json()["data"]["cadence_days"] == 30

    listed = client.get("/api/v1/settings/usuals").json()["data"]["items"]
    assert any(i["id"] == uid for i in listed)

    deleted = client.delete(f"/api/v1/settings/usuals/{uid}")
    assert deleted.status_code == 200 and deleted.json()["data"]["deleted"] is True


# --- ingredient aliases: "same shopping item" grouping (2026-09-10) --------------------


def _create_alias(client, alias_name, canonical_name):
    return client.post(
        "/api/v1/settings/ingredient-aliases",
        json={"alias_name": alias_name, "canonical_name": canonical_name},
    )


def test_create_ingredient_alias_happy_path(client):
    resp = _create_alias(client, "ZZ-Canola Oil", "ZZ-Vegetable Oil")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["alias_name"] == "zz-canola oil"  # normalised
    assert body["canonical_name"] == "zz-vegetable oil"


def test_create_ingredient_alias_duplicate_returns_structured_409(client):
    _create_alias(client, "ZZ-Dup-Alias", "ZZ-Canonical-A")
    resp = _create_alias(client, "zz-dup-alias", "zz-canonical-b")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_INGREDIENT_ALIAS"


def test_create_self_ingredient_alias_returns_structured_422(client):
    resp = _create_alias(client, "ZZ-Self-Alias", "zz-self-alias")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INGREDIENT_ALIAS"


def test_multiple_aliases_share_one_canonical(client):
    a = _create_alias(client, "ZZ-Multi-A", "ZZ-Multi-Canonical").json()["data"]
    b = _create_alias(client, "ZZ-Multi-B", "ZZ-Multi-Canonical").json()["data"]
    assert a["id"] != b["id"]

    listed = client.get("/api/v1/settings/ingredient-aliases?limit=500").json()["data"]["items"]
    mine = [r for r in listed if r["canonical_name"] == "zz-multi-canonical"]
    assert {r["alias_name"] for r in mine} == {"zz-multi-a", "zz-multi-b"}


def test_delete_ingredient_alias(client):
    row = _create_alias(client, "ZZ-DeleteMe-Alias", "ZZ-DeleteMe-Canonical").json()["data"]
    resp = client.delete(f"/api/v1/settings/ingredient-aliases/{row['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_update_ingredient_alias_not_found_returns_structured_404(client):
    resp = client.patch(
        "/api/v1/settings/ingredient-aliases/999999", json={"canonical_name": "x"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INGREDIENT_ALIAS_NOT_FOUND"


def test_create_ingredient_alias_with_equivalence_pair(client):
    resp = client.post(
        "/api/v1/settings/ingredient-aliases",
        json={
            "alias_name": "ZZ-Lemon Juice", "canonical_name": "ZZ-Lemon",
            "alias_qty": 3, "alias_unit": "TBSP", "canonical_qty": 1, "canonical_unit": None,
            "note": "roughly 3 tbsp per lemon",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["alias_qty"] == 3 and body["alias_unit"] == "tbsp"
    assert body["canonical_qty"] == 1 and body["canonical_unit"] is None
    assert body["note"] == "roughly 3 tbsp per lemon"


def test_create_ingredient_alias_half_pair_returns_422(client):
    resp = client.post(
        "/api/v1/settings/ingredient-aliases",
        json={"alias_name": "ZZ-Half-Pair", "canonical_name": "ZZ-Half-Canonical", "alias_qty": 2},
    )
    assert resp.status_code == 422


def test_usuals_duplicate_name_is_409(client):
    client.post("/api/v1/settings/usuals", json={"name": "ZZ Dish Soap", "cadence_days": 10})
    dup = client.post("/api/v1/settings/usuals", json={"name": "zz dish soap", "cadence_days": 5})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_USUAL_ITEM_NAME"


def test_usuals_reject_zero_cadence(client):
    resp = client.post("/api/v1/settings/usuals", json={"name": "ZZ Bad", "cadence_days": 0})
    assert resp.status_code == 422


def test_usuals_update_missing_is_404(client):
    resp = client.patch("/api/v1/settings/usuals/999999", json={"cadence_days": 7})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USUAL_ITEM_NOT_FOUND"


# --- unit synonyms: spelling canonicalisation (2026-09-12) -----------------------------


def test_create_unit_synonym_happy_path(client):
    resp = client.post(
        "/api/v1/settings/unit-synonyms",
        json={"alias_unit": "ZZ-Grams", "canonical_unit": "ZZ-G"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["alias_unit"] == "zz-gram"  # normalised through strip_plural too
    assert body["canonical_unit"] == "zz-g"


def test_create_unit_synonym_duplicate_returns_409(client):
    client.post(
        "/api/v1/settings/unit-synonyms",
        json={"alias_unit": "ZZ-Dup-Unit", "canonical_unit": "ZZ-A"},
    )
    resp = client.post(
        "/api/v1/settings/unit-synonyms",
        json={"alias_unit": "zz-dup-unit", "canonical_unit": "zz-b"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_UNIT_SYNONYM"


def test_create_self_unit_synonym_returns_422(client):
    resp = client.post(
        "/api/v1/settings/unit-synonyms",
        json={"alias_unit": "ZZ-Self-Unit", "canonical_unit": "zz-self-unit"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_UNIT_SYNONYM"


def test_delete_unit_synonym(client):
    row = client.post(
        "/api/v1/settings/unit-synonyms",
        json={"alias_unit": "ZZ-DeleteMe-Unit", "canonical_unit": "zz-target"},
    ).json()["data"]
    resp = client.delete(f"/api/v1/settings/unit-synonyms/{row['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_update_unit_synonym_not_found_returns_404(client):
    resp = client.patch(
        "/api/v1/settings/unit-synonyms/999999", json={"canonical_unit": "x"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "UNIT_SYNONYM_NOT_FOUND"


# --- coarse ingredients: skip quantity math entirely (2026-09-12) ----------------------


def test_create_coarse_ingredient_happy_path(client):
    resp = client.post(
        "/api/v1/settings/coarse-ingredients",
        json={"name": "ZZ-Parsley", "purchase_label": "bunch"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["name"] == "zz-parsley"
    assert body["purchase_label"] == "bunch"
    assert body["recipes_per_pack"] == 3  # default


def test_create_coarse_ingredient_duplicate_returns_409(client):
    client.post("/api/v1/settings/coarse-ingredients", json={"name": "ZZ-Dup-Coarse"})
    resp = client.post("/api/v1/settings/coarse-ingredients", json={"name": "zz-dup-coarse"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_COARSE_INGREDIENT"


def test_create_coarse_ingredient_rejects_zero_recipes_per_pack(client):
    resp = client.post(
        "/api/v1/settings/coarse-ingredients",
        json={"name": "ZZ-Bad-Coarse", "recipes_per_pack": 0},
    )
    assert resp.status_code == 422


def test_delete_coarse_ingredient(client):
    row = client.post(
        "/api/v1/settings/coarse-ingredients", json={"name": "ZZ-DeleteMe-Coarse"}
    ).json()["data"]
    resp = client.delete(f"/api/v1/settings/coarse-ingredients/{row['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_update_coarse_ingredient_not_found_returns_404(client):
    resp = client.patch(
        "/api/v1/settings/coarse-ingredients/999999", json={"purchase_label": "bunch"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "COARSE_INGREDIENT_NOT_FOUND"

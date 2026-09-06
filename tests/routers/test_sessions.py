"""Smoke tests for /api/v1/sessions — happy path + one error path per feature
(CLAUDE.md > Code Architecture & Maintainability). Deep coverage is in
tests/services/test_sessions.py.

conftest.py shares one SQLite file across the session, so assert on the specific
rows this test made, not on totals.
"""

from __future__ import annotations


def _recipe(client, name):
    return client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "source_type": "manual",
            "ingredients": [{"name": "thing", "quantity": 1, "unit": "g"}],
            "allow_duplicate": True,
        },
    ).json()["data"]


def _session(client, label="ZZ-Router-Session"):
    return client.post("/api/v1/sessions", json={"label": label}).json()["data"]


def test_create_and_get_session(client):
    created = _session(client, "ZZ-Create-Get")
    assert created["status"] == "active"
    assert created["recipes"] == []

    resp = client.get(f"/api/v1/sessions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == created["id"]


def test_get_session_not_found_structured_404(client):
    resp = client.get("/api/v1/sessions/999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_list_sessions_includes_created_with_slot_count(client):
    s = _session(client, "ZZ-List-Session")
    r = _recipe(client, "ZZ-List-Session-Recipe")
    client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]})

    resp = client.get("/api/v1/sessions?limit=200")
    assert resp.status_code == 200
    row = next(x for x in resp.json()["data"]["items"] if x["id"] == s["id"])
    assert row["slot_count"] == 1


def test_add_recipe_slot_defaults_servings_and_returns_recipe_name(client):
    s = _session(client, "ZZ-AddRecipe")
    r = _recipe(client, "ZZ-AddRecipe-Recipe")

    resp = client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]})
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["slot_type"] == "recipe"
    assert body["scaled_servings"] == 4  # DEFAULT_TARGET_SERVINGS
    assert body["recipe_name"] == "ZZ-AddRecipe-Recipe"


def test_add_recipe_slot_unknown_recipe_structured_404(client):
    s = _session(client, "ZZ-BadRecipe")
    resp = client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": 999999})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RECIPE_NOT_FOUND"


def test_add_leftovers_slot(client):
    s = _session(client, "ZZ-Leftovers")
    resp = client.post(f"/api/v1/sessions/{s['id']}/leftovers", json={"day_of_week": 6})
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["slot_type"] == "leftovers"
    assert body["recipe_id"] is None
    assert body["scaled_servings"] == 0
    assert body["recipe_name"] is None


def test_update_and_delete_slot(client):
    s = _session(client, "ZZ-UpdDel")
    r = _recipe(client, "ZZ-UpdDel-Recipe")
    slot = client.post(
        f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]}
    ).json()["data"]

    upd = client.patch(
        f"/api/v1/sessions/{s['id']}/slots/{slot['id']}",
        json={"scaled_servings": 2, "day_of_week": 1},
    )
    assert upd.status_code == 200
    assert upd.json()["data"]["scaled_servings"] == 2

    dele = client.delete(f"/api/v1/sessions/{s['id']}/slots/{slot['id']}")
    assert dele.status_code == 200
    assert dele.json()["data"]["deleted"] is True


def test_update_slot_not_found_structured_404(client):
    s = _session(client, "ZZ-SlotMiss")
    resp = client.patch(
        f"/api/v1/sessions/{s['id']}/slots/999999", json={"scaled_servings": 2}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_SLOT_NOT_FOUND"


def test_reorder_slots(client):
    s = _session(client, "ZZ-Reorder")
    ids = []
    for n in ("A", "B", "C"):
        r = _recipe(client, f"ZZ-Reorder-{n}")
        ids.append(
            client.post(
                f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]}
            ).json()["data"]["id"]
        )

    resp = client.put(
        f"/api/v1/sessions/{s['id']}/slots/order", json={"ordered_ids": [ids[2], ids[0], ids[1]]}
    )
    assert resp.status_code == 200
    assert [x["id"] for x in resp.json()["data"]] == [ids[2], ids[0], ids[1]]
    assert [x["sort_order"] for x in resp.json()["data"]] == [0, 1, 2]


def test_reorder_slots_mismatch_structured_422(client):
    s = _session(client, "ZZ-ReorderBad")
    r = _recipe(client, "ZZ-ReorderBad-R")
    slot = client.post(
        f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]}
    ).json()["data"]

    resp = client.put(
        f"/api/v1/sessions/{s['id']}/slots/order", json={"ordered_ids": [slot["id"], 424242]}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SLOT_ORDER_MISMATCH"


def test_archive_session_and_status_filter(client):
    s = _session(client, "ZZ-Archive-Session")
    resp = client.post(f"/api/v1/sessions/{s['id']}/archive")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "archived"

    listed = client.get("/api/v1/sessions?status=archived&limit=200").json()["data"]["items"]
    assert any(x["id"] == s["id"] for x in listed)


# --- consolidate endpoint (Chunk 4.6) ------------------------------------


def test_consolidate_endpoint_returns_checklist(client):
    s = _session(client, "ZZ-Consolidate")
    r = client.post(
        "/api/v1/recipes",
        json={
            "name": "ZZ-Consolidate-Recipe",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [
                {"name": "beef mince", "quantity": 500, "unit": "g"},
                {"name": "onion", "quantity": 2, "unit": None},
            ],
            "allow_duplicate": True,
        },
    ).json()["data"]
    client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"], "scaled_servings": 4})

    resp = client.post(f"/api/v1/sessions/{s['id']}/consolidate", json={})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["session_id"] == s["id"]
    names = {i["ingredient_name"]: i for i in body["items"]}
    assert names["onion"]["total_quantity"] == 2
    assert names["beef mince"]["total_quantity"] == 500
    # beef mince is seeded as a 500g pack -> resolves
    assert names["beef mince"]["display_qty"] == "1 × 500g pack"


def test_consolidate_endpoint_unknown_session_404(client):
    resp = client.post("/api/v1/sessions/999999/consolidate", json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_consolidate_endpoint_multi_pack_eggs(client):
    # eggs are seeded with two pack sizes (half dozen + dozen) -> several-rows path
    s = _session(client, "ZZ-Consolidate-Eggs")
    r = client.post(
        "/api/v1/recipes",
        json={
            "name": "ZZ-Eggs-Recipe",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": [{"name": "eggs", "quantity": 8, "unit": None}],
            "allow_duplicate": True,
        },
    ).json()["data"]
    client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"], "scaled_servings": 4})

    resp = client.post(f"/api/v1/sessions/{s['id']}/consolidate", json={})
    eggs = next(i for i in resp.json()["data"]["items"] if i["ingredient_name"] == "eggs")
    assert eggs["display_qty"] == "1 × dozen"  # 8 eggs -> a dozen beats a half-dozen


def test_consolidate_endpoint_session_override(client):
    s = _session(client, "ZZ-Consolidate-Override")
    r = client.post(
        "/api/v1/recipes",
        json={
            "name": "ZZ-Override-Recipe",
            "source_type": "manual",
            "ingredients": [{"name": "zz-bulgarian feta", "quantity": 100, "unit": "g"}],
            "allow_duplicate": True,
        },
    ).json()["data"]
    client.post(f"/api/v1/sessions/{s['id']}/recipes", json={"recipe_id": r["id"]})

    resp = client.post(
        f"/api/v1/sessions/{s['id']}/consolidate",
        json={"overrides": [{"original_name": "zz-bulgarian feta", "substitute_name": "zz-plain feta"}]},
    )
    names = [i["ingredient_name"] for i in resp.json()["data"]["items"]]
    assert "zz-plain feta" in names
    assert "zz-bulgarian feta" not in names

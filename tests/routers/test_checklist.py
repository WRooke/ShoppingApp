"""Router smoke tests for /api/v1/checklist (Phase 5 Chunk 5.3). Happy path + error paths.
AnyList is forced into fake mode where a load actually needs it.
"""

from __future__ import annotations

import pytest

from app.services import anylist_client


@pytest.fixture()
def fake_anylist(monkeypatch):
    monkeypatch.setattr(anylist_client.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_target_list_name", "TestList", raising=False)
    anylist_client.reset_client()
    yield
    anylist_client.reset_client()


def _session_with_checklist(client, ingredients):
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Checklist Router Recipe",
            "source_type": "manual",
            "base_servings": 4,
            "ingredients": ingredients,
            "allow_duplicate": True,
        },
    ).json()["data"]
    sid = client.post("/api/v1/sessions", json={"label": "cl"}).json()["data"]["id"]
    client.post(f"/api/v1/sessions/{sid}/recipes", json={"recipe_id": recipe["id"], "scaled_servings": 4})
    client.post(f"/api/v1/sessions/{sid}/consolidate", json={})
    return sid


def test_load_before_consolidate_is_409(client):
    sid = client.post("/api/v1/sessions", json={"label": "empty"}).json()["data"]["id"]
    resp = client.get(f"/api/v1/checklist/{sid}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CHECKLIST_NOT_CONSOLIDATED"


def test_load_returns_envelope_with_items_and_anylist_status(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "milk", "quantity": 1, "unit": "L"},
                 {"name": "zz-router-passata", "quantity": 400, "unit": "g"}]
    )
    resp = client.get(f"/api/v1/checklist/{sid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == sid
    assert data["anylist_ok"] is True
    names = {i["ingredient_name"]: i for i in data["items"]}
    assert names["milk"]["already_on_anylist"] is True
    assert names["milk"]["have_it"] == "yes"  # pre-ticked from the fake list
    assert names["zz-router-passata"]["already_on_anylist"] is False


def test_patch_item_updates_state(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-router-x", "quantity": 2, "unit": None}])
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    resp = client.patch(
        f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "no", "add_to_list": True}
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["have_it"] == "no" and body["add_to_list"] is True


def test_patch_unknown_item_is_404(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-router-y", "quantity": 1, "unit": None}])
    resp = client.patch(f"/api/v1/checklist/{sid}/items/999999", json={"have_it": "yes"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CHECKLIST_ITEM_NOT_FOUND"


def test_patch_item_rejects_bad_have_it_value(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-router-z", "quantity": 1, "unit": None}])
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    resp = client.patch(f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "maybe"})
    assert resp.status_code == 422


def test_resolve_needs_review_item(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-router-cream", "quantity": 100, "unit": "g"},
                 {"name": "zz-router-cream", "quantity": 200, "unit": "ml"}]
    )
    item = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]
    assert item["needs_review"] is True
    resp = client.post(
        f"/api/v1/checklist/{sid}/items/{item['id']}/resolve",
        json={"total_quantity": 300, "total_unit": "ml"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["needs_review"] is False
    assert body["total_quantity"] == 300 and body["total_unit"] == "ml"

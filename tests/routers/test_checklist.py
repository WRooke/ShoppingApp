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


def test_push_marks_session_pushed_and_refuses_re_push(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-push-passata", "quantity": 400, "unit": "g"}])
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    client.patch(f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "no"})

    pushed = client.post(f"/api/v1/checklist/{sid}/push", json={"usual_ids": []})
    assert pushed.status_code == 200
    body = pushed.json()["data"]
    assert "Zz-Push-Passata" in body["added"] and body["confirmed"] is True

    session = client.get(f"/api/v1/sessions/{sid}").json()["data"]
    assert session["status"] == "pushed" and session["pushed_at"] is not None

    again = client.post(f"/api/v1/checklist/{sid}/push", json={"usual_ids": []})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "SESSION_ALREADY_PUSHED"

    forced = client.post(f"/api/v1/checklist/{sid}/push?force=true", json={"usual_ids": []})
    assert forced.status_code == 200


def test_load_survives_malformed_review_options_json(client, fake_anylist):
    """2026-09-17 prod bug reproduction — a needs_review row whose review_options_json was
    written by an earlier/different shape (here: an element missing 'quantity') used to 500
    the whole checklist load at the router's ChecklistItemRead.model_validate(row) step,
    since ReviewOptionRead.quantity is required with no default. Every subsequent load of
    that same session failed identically until the row was fixed by hand — matching the
    diagnostics log signature (repeated "Unhandled exception on GET /api/v1/checklist/{id}").
    """
    sid = _session_with_checklist(
        client, [{"name": "zz-router-malformed", "quantity": 100, "unit": "g"},
                 {"name": "zz-router-malformed", "quantity": 200, "unit": "ml"}]
    )
    item = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]
    assert item["needs_review"] is True

    import app.database as database
    from app.models.planning import SessionChecklistItem

    db = database.SessionLocal()
    try:
        row = db.get(SessionChecklistItem, item["id"])
        row.review_options_json = '[{"unit": "g"}]'  # malformed: no 'quantity'
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/checklist/{sid}")
    assert resp.status_code == 200
    reloaded = next(i for i in resp.json()["data"]["items"] if i["id"] == item["id"])
    assert reloaded["review_options"] == []  # malformed element dropped, not raised


def test_load_after_push_with_usuals_survives_naive_aware_round_trip(client, fake_anylist):
    """2026-09-19 prod bug reproduction — GET /api/v1/checklist/{id} 500'd with `TypeError:
    can't compare offset-naive and offset-aware datetimes` any time a usual item had a
    non-null last_added_at, because the value re-fetched from SQLite came back naive while
    is_due()'s `now` was a fresh, aware utcnow() (app/services/usuals.py). The `client`
    fixture repoints app.database.SessionLocal at a real file-backed test DB per session
    (see conftest.py), so each request below is a genuine round trip through SQLite — an
    in-memory-only assertion wouldn't have caught the original bug.
    """
    due_soon = client.post(
        "/api/v1/settings/usuals", json={"name": "zz-router-paper-towels", "cadence_days": 7}
    ).json()["data"]
    overdue = client.post(
        "/api/v1/settings/usuals", json={"name": "zz-router-light-bulbs", "cadence_days": 30}
    ).json()["data"]

    sid = _session_with_checklist(client, [{"name": "zz-router-usuals-milk", "quantity": 1, "unit": "L"}])
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    client.patch(f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "no"})

    pushed = client.post(
        f"/api/v1/checklist/{sid}/push", json={"usual_ids": [due_soon["id"], overdue["id"]]}
    )
    assert pushed.status_code == 200  # stamps both usuals' last_added_at via mark_added()

    # Back-date "overdue" well past its cadence, directly in the DB — same pattern as
    # test_load_survives_malformed_review_options_json above.
    import app.database as database
    from app.models.catalog import UsualItem

    db = database.SessionLocal()
    try:
        row = db.get(UsualItem, overdue["id"])
        row.last_added_at = row.last_added_at.replace(year=row.last_added_at.year - 1)
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/checklist/{sid}")
    assert resp.status_code == 200  # not 500 — this is the actual regression check
    usual_names = {u["name"] for u in resp.json()["data"]["usuals"]}
    assert usual_names == {"zz-router-light-bulbs"}  # overdue is due; due_soon just got added


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

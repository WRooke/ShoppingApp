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
    # "eggs" (not "milk") — 2026-09-27 (Fix 5, F5.2) "milk" is now aliased to "full cream milk"
    # (a real, accepted household preference), which would no longer fuzzy-match the fake
    # AnyList seed's "milk" item. "eggs" -> "egg" (Fix 1's own plural-strip, unrelated to any
    # alias) still exercises the exact same pre-tick/fuzzy-match path this test is actually for.
    sid = _session_with_checklist(
        client, [{"name": "eggs", "quantity": 1, "unit": None},
                 {"name": "zz-router-passata", "quantity": 400, "unit": "g"}]
    )
    resp = client.get(f"/api/v1/checklist/{sid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == sid
    assert data["anylist_ok"] is True
    names = {i["ingredient_name"]: i for i in data["items"]}
    assert names["egg"]["already_on_anylist"] is True
    assert names["egg"]["have_it"] == "yes"  # pre-ticked from the fake list
    # 2026-09-27 — the shared normaliser folds hyphens to a space.
    assert names["zz router passata"]["already_on_anylist"] is False


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
    # 2026-09-27 — hyphen folded to a space by the shared normaliser before AnyList push's
    # own .title() call: "zz-push-passata" -> "zz push passata" -> "Zz Push Passata".
    assert "Zz Push Passata" in body["added"] and body["confirmed"] is True

    session = client.get(f"/api/v1/sessions/{sid}").json()["data"]
    assert session["status"] == "pushed" and session["pushed_at"] is not None

    again = client.post(f"/api/v1/checklist/{sid}/push", json={"usual_ids": []})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "SESSION_ALREADY_PUSHED"

    forced = client.post(f"/api/v1/checklist/{sid}/push?force=true", json={"usual_ids": []})
    assert forced.status_code == 200


# --- push progress polling (2026-09-23 — real per-item push progress UI) -----------------


def test_push_progress_reflects_a_real_push(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-push-progress-eggs", "quantity": 6, "unit": None}])
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    client.patch(f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "no"})

    pushed = client.post(
        f"/api/v1/checklist/{sid}/push",
        json={"usual_ids": [], "progress_token": "push-router-tok-1"},
    )
    assert pushed.status_code == 200

    progress_resp = client.get("/api/v1/checklist/push/progress/push-router-tok-1")
    assert progress_resp.status_code == 200
    body = progress_resp.json()
    assert body["ok"] is True
    assert body["data"]["steps"][0]["status"] == "done"


def test_push_progress_unknown_token_returns_structured_404(client):
    resp = client.get("/api/v1/checklist/push/progress/never-existed")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROGRESS_TOKEN_NOT_FOUND"


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
    # normalised (hyphen -> space, "bulbs" -> "bulb")
    assert usual_names == {"zz router light bulb"}  # overdue is due; due_soon just got added


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


# --- merge (Fix 3, F3.3) -----------------------------------------------------------------


def test_merge_name_only_not_remembered_collapses_two_rows(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-carrot", "quantity": 2, "unit": None},
                 {"name": "zz-merge-orange-carrot", "quantity": 3, "unit": None}]
    )
    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge carrot", "zz merge orange carrot"],
            "canonical_name": "zz merge carrot",
            "remember": False,
        },
    )
    assert resp.status_code == 200
    names = {i["ingredient_name"] for i in resp.json()["data"]["items"]}
    assert "zz merge carrot" in names
    assert "zz merge orange carrot" not in names

    reloaded = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"]
    merged = next(i for i in reloaded if i["ingredient_name"] == "zz merge carrot")
    assert merged["total_quantity"] == 5  # 2 + 3


def test_merge_with_pair_converts_amount_and_shows_a_conversion_note(client, fake_anylist):
    sid = _session_with_checklist(client, [{"name": "zz-merge-corn", "quantity": 4, "unit": "cob"}])
    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge corn", "zz merge canned corn"],
            "canonical_name": "zz merge canned corn",
            "remember": False,
            "alias_qty": 2, "alias_unit": "cob", "canonical_qty": 1, "canonical_unit": "can",
        },
    )
    assert resp.status_code == 200
    item = next(i for i in resp.json()["data"]["items"] if i["ingredient_name"] == "zz merge canned corn")
    assert item["total_quantity"] == 2 and item["total_unit"] == "can"
    assert "from" in (item["note"] or "").lower()


def test_merge_remember_true_creates_a_durable_alias(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-remember-a", "quantity": 1, "unit": None},
                 {"name": "zz-merge-remember-b", "quantity": 2, "unit": None}]
    )
    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge remember a", "zz merge remember b"],
            "canonical_name": "zz merge remember a",
            "remember": True,
        },
    )
    assert resp.status_code == 200

    # Confirmed via a second, unrelated session -- the alias is durable, not session-scoped.
    sid2 = _session_with_checklist(client, [{"name": "zz-merge-remember-b", "quantity": 5, "unit": None}])
    items2 = client.get(f"/api/v1/checklist/{sid2}").json()["data"]["items"]
    assert [i["ingredient_name"] for i in items2] == ["zz merge remember a"]
    assert items2[0]["total_quantity"] == 5


def test_merge_remember_false_only_affects_this_session(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-scoped-a", "quantity": 1, "unit": None},
                 {"name": "zz-merge-scoped-b", "quantity": 2, "unit": None}]
    )
    client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge scoped a", "zz merge scoped b"],
            "canonical_name": "zz merge scoped a",
            "remember": False,
        },
    )
    sid2 = _session_with_checklist(client, [{"name": "zz-merge-scoped-b", "quantity": 5, "unit": None}])
    items2 = client.get(f"/api/v1/checklist/{sid2}").json()["data"]["items"]
    assert [i["ingredient_name"] for i in items2] == ["zz merge scoped b"]  # untouched


def test_merge_refused_once_session_is_pushed(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-pushed-a", "quantity": 1, "unit": None},
                 {"name": "zz-merge-pushed-b", "quantity": 2, "unit": None}]
    )
    item_id = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"][0]["id"]
    client.patch(f"/api/v1/checklist/{sid}/items/{item_id}", json={"have_it": "no"})
    pushed = client.post(f"/api/v1/checklist/{sid}/push", json={"usual_ids": []})
    assert pushed.status_code == 200

    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge pushed a", "zz merge pushed b"],
            "canonical_name": "zz merge pushed a",
            "remember": False,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SESSION_ALREADY_PUSHED"


def test_merge_remember_true_onto_an_already_aliased_name_is_a_structured_409(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-dup-a", "quantity": 1, "unit": None},
                 {"name": "zz-merge-dup-b", "quantity": 2, "unit": None}]
    )
    client.post(
        "/api/v1/settings/ingredient-aliases",
        json={"alias_name": "zz merge dup b", "canonical_name": "zz something else"},
    )
    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge dup a", "zz merge dup b"],
            "canonical_name": "zz merge dup a",
            "remember": True,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_INGREDIENT_ALIAS"


def test_merge_carries_forward_the_strongest_have_it_and_add_to_list(client, fake_anylist):
    sid = _session_with_checklist(
        client, [{"name": "zz-merge-state-a", "quantity": 1, "unit": None},
                 {"name": "zz-merge-state-b", "quantity": 2, "unit": None}]
    )
    items = client.get(f"/api/v1/checklist/{sid}").json()["data"]["items"]
    a = next(i for i in items if i["ingredient_name"] == "zz merge state a")
    b = next(i for i in items if i["ingredient_name"] == "zz merge state b")
    # "a" is set to "no" (add_to_list True); "b" stays "unknown" -- "no" must win the merge.
    client.patch(f"/api/v1/checklist/{sid}/items/{a['id']}", json={"have_it": "no", "add_to_list": True})

    resp = client.post(
        f"/api/v1/checklist/{sid}/merge",
        json={
            "item_names": ["zz merge state a", "zz merge state b"],
            "canonical_name": "zz merge state b",  # keep the OTHER name, still "unknown"
            "remember": False,
        },
    )
    assert resp.status_code == 200
    merged = next(i for i in resp.json()["data"]["items"] if i["ingredient_name"] == "zz merge state b")
    assert merged["have_it"] == "no" and merged["add_to_list"] is True

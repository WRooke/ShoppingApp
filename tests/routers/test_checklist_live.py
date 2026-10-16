"""Live checklist across phones (Chunk 6.7, user-feedback batch, polish batch 3, item C): the revision counter,
the long-poll /changes endpoint and the AnyList-free /items re-read."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.routers import checklist as checklist_router
from app.services import anylist_client, checklist_revisions


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(checklist_router, "LONG_POLL_SECONDS", 0.5)
    monkeypatch.setattr(checklist_router, "LONG_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(anylist_client.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(anylist_client.settings, "anylist_target_list_name", "TestList", raising=False)
    anylist_client.reset_client()
    yield
    anylist_client.reset_client()


def _plan(client):
    recipe = client.post(
        "/api/v1/recipes",
        json={"name": "Live Recipe", "source_type": "manual", "base_servings": 4,
              "ingredients": [{"name": "zz-live-tomato", "quantity": 3, "unit": None}],
              "allow_duplicate": True},
    ).json()["data"]
    sid = client.post("/api/v1/sessions", json={"label": "live"}).json()["data"]["id"]
    client.post(f"/api/v1/sessions/{sid}/recipes", json={"recipe_id": recipe["id"], "scaled_servings": 4})
    return sid


def _changes(client, sid, epoch, rev):
    return client.get(f"/api/v1/checklist/{sid}/changes", params={"epoch": epoch, "rev": rev}).json()["data"]


def test_load_reports_where_to_start_and_a_quiet_poll_times_out_unchanged(client):
    sid = _plan(client)
    load = client.get(f"/api/v1/checklist/{sid}").json()["data"]
    start = time.monotonic()
    out = _changes(client, sid, load["epoch"], load["rev"])
    assert out["changed"] is False and (out["epoch"], out["rev"]) == (load["epoch"], load["rev"])
    assert time.monotonic() - start >= 0.4  # it really waited


def test_a_stale_revision_or_another_servers_epoch_answers_immediately(client):
    sid = _plan(client)
    load = client.get(f"/api/v1/checklist/{sid}").json()["data"]
    start = time.monotonic()
    assert _changes(client, sid, load["epoch"], load["rev"] - 1)["changed"] is True
    assert _changes(client, sid, "some-older-server", load["rev"])["changed"] is True
    assert time.monotonic() - start < 0.4


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("patch", "/api/v1/checklist/{sid}/items/{iid}", {"have_it": "no", "add_to_list": True}),
        ("post", "/api/v1/checklist/{sid}/items/{iid}/have-some", {"quantity": 1}),
        ("post", "/api/v1/checklist/{sid}/items/{iid}/coarse", {"purchase_label": "bunch", "recipes_per_pack": 2, "remember": False}),
        ("post", "/api/v1/checklist/{sid}/push", None),
        ("patch", "/api/v1/sessions/{sid}", {"label": "renamed"}),
    ],
)
def test_every_kind_of_edit_bumps_the_revision(client, method, path, body):
    sid = _plan(client)
    load = client.get(f"/api/v1/checklist/{sid}").json()["data"]
    iid = load["items"][0]["id"]
    getattr(client, method)(path.format(sid=sid, iid=iid), **({"json": body} if body is not None else {}))
    assert checklist_revisions.current(sid)[1] > load["rev"]


def test_a_plain_load_never_looks_like_an_edit(client):
    sid = _plan(client)
    first = client.get(f"/api/v1/checklist/{sid}").json()["data"]
    client.get(f"/api/v1/checklist/{sid}")
    client.get(f"/api/v1/checklist/{sid}/items")
    assert checklist_revisions.current(sid)[1] == first["rev"]


def test_skipping_a_usual_wakes_every_plan(client):
    sid = _plan(client)
    before = checklist_revisions.current(sid)[1]
    checklist_revisions.bump_all()
    assert checklist_revisions.current(sid)[1] == before + 1


def test_items_reread_is_complete_and_never_reads_anylist(client, monkeypatch):
    sid = _plan(client)
    client.get(f"/api/v1/checklist/{sid}")  # populate
    calls = []
    monkeypatch.setattr(anylist_client, "get_items", lambda *a, **k: calls.append(1) or [])
    data = client.get(f"/api/v1/checklist/{sid}/items").json()["data"]
    assert calls == []
    assert data["items"][0]["recipe_breakdown"] and "epoch" in data and "usuals" in data


def test_a_disconnecting_phone_stops_the_wait():
    # The loop's own exit: not hanging the full poll when the client has gone.
    async def go():
        class Gone:
            async def is_disconnected(self):
                return True

        start = time.monotonic()
        epoch, rev = checklist_revisions.current(1)
        out = await checklist_router.checklist_changes(1, Gone(), epoch=epoch, rev=rev)
        return time.monotonic() - start, out

    elapsed, out = asyncio.run(go())
    # Unchanged revision, so only the disconnect can end the wait early (poll is 0.5 s here).
    assert elapsed < 0.2 and out["data"]["changed"] is False

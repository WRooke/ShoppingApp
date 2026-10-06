"""The whole push — `checklist.load_checklist` + `checklist.push_to_anylist` + the REAL connector —
over the stateful fake AnyList server (tests/services/anylist_fake_server.py).

Scenario tests for each defect found in the Chunk 6.7 investigation (docs/anylist-push.md), then a
seeded fuzz run. The oracle is the same everywhere and is independent of what the push claims:
after a push, EVERY row the user marked "Need it" has exactly one ACTIVE (uncrossed) matching item on
the list with the wanted quantity — or the push said, by name, that it failed.
"""

from __future__ import annotations

import json
import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.history import ShoppingHistory
from app.schemas.ingredient_aliases import IngredientAliasCreate
from app.schemas.recipes import RecipeCreate, RecipeIngredientCreate
from app.schemas.sessions import PlanningSessionCreate, SessionRecipeCreate
from app.schemas.usuals import UsualItemCreate
from app.services import anylist_client as ac
from app.services import checklist as cl
from app.services import ingredient_aliases as aliases_service
from app.services import progress_tracker
from app.services import recipes as recipes_service
from app.services import sessions as sessions_service
from app.services import usuals as usuals_service
from tests.services.anylist_fake_server import FakeAnyListServer


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def server(monkeypatch):
    srv = FakeAnyListServer()
    srv.install(monkeypatch)
    yield srv
    ac.reset_client()


def _recipe(db, name, ings):
    return recipes_service.create_recipe(
        db,
        RecipeCreate(name=name, source_type="manual", base_servings=4,
                     ingredients=[RecipeIngredientCreate(**i) for i in ings]),
        allow_duplicate=True,
    )


def _session(db, *recipes_ings):
    s = sessions_service.create_session(db, PlanningSessionCreate())
    for n, ings in enumerate(recipes_ings):
        r = _recipe(db, f"R{n}", ings)
        sessions_service.add_session_recipe(db, s.id, SessionRecipeCreate(recipe_id=r.id, scaled_servings=4))
    sessions_service.consolidate_session(db, s.id)
    return s


def _rows(db, s):
    return {r.ingredient_name: r for r in sessions_service.get_session(db, s.id).checklist_items}


def _need_all(db, s):
    for r in list(_rows(db, s).values()):
        cl.update_item(db, s.id, r.id, have_it="no", add_to_list=True)


def _need_rows(db, s):
    return [r for r in sessions_service.get_session(db, s.id).checklist_items
            if r.add_to_list or r.have_it == "no"]


def _active_matches(r, items):
    return [i for i in items if not i.checked and cl._names_match(r.ingredient_name, i.name)]


def _oracle(db, s, server, pushed: dict | None = None, before: dict | None = None) -> list[str]:
    """Every Need-it row must be on the list ACTIVE with the wanted quantity. By default exactly
    once; with `before` ({row id: active matches before the push}) a duplicate that already
    existed (e.g. made on the phone) is tolerated but the push must never ADD one."""
    problems = []
    items = ac.get_items()
    for r in _need_rows(db, s):
        active = _active_matches(r, items)
        want = cl._anylist_quantity(r)
        limit = 1 if before is None else max(1, before.get(r.id, 0))
        if not active or len(active) > limit:
            problems.append(f"{r.ingredient_name!r}: {len(active)} active item(s) on the list (allowed 1..{limit})")
        elif not any((a.quantity or "").strip().casefold() == (want or "").strip().casefold() for a in active):
            problems.append(f"{r.ingredient_name!r}: quantity {[a.quantity for a in active]!r}, wanted {want!r}")
    if pushed is not None:
        for r in _need_rows(db, s):
            if not [i for i in pushed["items"] if i["key"] == f"item:{r.id}"]:
                problems.append(f"{r.ingredient_name!r}: missing from the push result")
        if pushed["confirmed"] and problems:
            problems.append("FALSE CONFIRM")
    return problems


# --- defect A: decisions survive renames -------------------------------------------------


def test_need_it_survives_an_alias_added_between_visits_and_is_pushed(db, server):
    server.phone_add("butter", "1 block", checked=False)  # something that WOULD pre-tick "Have it"
    s = _session(db, [{"name": "unsalted butter", "quantity": 1, "unit": "block"}])
    cl.load_checklist(db, s.id)
    row = _rows(db, s)["unsalted butter"]
    cl.update_item(db, s.id, row.id, have_it="no", add_to_list=True)

    aliases_service.create_alias(db, IngredientAliasCreate(alias_name="unsalted butter", canonical_name="butter"))
    items, ok, _d, _b = cl.load_checklist(db, s.id)  # the load that used to pre-tick it "Have it"
    butter = next(i for i in items if i.ingredient_name == "butter")
    assert (butter.have_it, butter.add_to_list) == ("no", True)

    res = cl.push_to_anylist(db, s.id)
    assert res["confirmed"] and not _oracle(db, s, server, res)


# --- defect B: crossed-off items -----------------------------------------------------------


def test_crossed_off_item_is_not_on_the_list_does_not_preticks_and_is_uncrossed_by_the_push(db, server):
    ident = server.phone_add("Milk", "1 L", note="household note", checked=True)
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    items, ok, _d, _b = cl.load_checklist(db, s.id)
    milk = items[0]
    assert milk.already_on_anylist is False and milk.have_it == "unknown"  # not pre-ticked "Have it"

    cl.update_item(db, s.id, milk.id, have_it="no", add_to_list=True)
    res = cl.push_to_anylist(db, s.id)

    assert res["uncrossed"] == ["Milk"] and res["confirmed"]
    assert server.items[ident]["checked"] is False  # un-crossed IN PLACE...
    assert server.items[ident]["note"] == "household note"  # ...so what the household typed survives
    assert len(server.named("milk")) == 1
    assert not _oracle(db, s, server, res)


def test_an_active_item_is_preferred_over_a_crossed_off_duplicate_whatever_the_list_order(db, server):
    old = server.phone_add("Milk", "1 L", checked=True)  # listed FIRST
    live = server.phone_add("Milk", "1 L")
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    items, _ok, _d, _b = cl.load_checklist(db, s.id)
    assert items[0].anylist_item_id == live
    cl.update_item(db, s.id, items[0].id, have_it="no", add_to_list=True)
    res = cl.push_to_anylist(db, s.id)
    assert res["already_active"] == ["Milk"] and server.posts == []
    assert server.items[old]["checked"] is True  # the old crossed-off one is left alone


def test_a_household_note_survives_both_an_uncross_and_a_quantity_change(db, server):
    a = server.phone_add("Milk", "1 L", note="organic only", checked=True)
    b = server.phone_add("Eggs", "2 dozen", note="free range")
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}, {"name": "egg", "quantity": 6, "unit": "x"}])
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id)
    assert res["confirmed"]
    assert server.items[a]["note"] == "organic only" and server.items[a]["checked"] is False  # in place
    (eggs,) = server.active("egg")
    assert eggs["note"] == "free range"  # replaced for the new quantity, old note carried across
    assert b not in server.items


# --- defect E: failure handling ------------------------------------------------------------


def test_a_failed_push_leaves_the_session_re_pushable_and_the_retry_heals_without_duplicates(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}, {"name": "eggs", "quantity": 6, "unit": None}])
    _need_all(db, s)
    server.post_rule = lambda n, op: "drop"  # AnyList swallows every write
    res = cl.push_to_anylist(db, s.id, progress_token="tok-fail")

    assert res["confirmed"] is False and sorted(res["failed"]) == ["Eggs", "Milk"]
    assert all(it["reason"] for it in res["items"] if it["outcome"] == "failed")
    assert res["session_status"] != "pushed"  # so the user can simply push again — no "already pushed" prompt
    assert progress_tracker.get_stage("tok-fail") == "needs-attention"
    assert {r["status"] for r in progress_tracker.get("tok-fail")} == {"failed"}

    server.post_rule = None  # AnyList recovers
    res2 = cl.push_to_anylist(db, s.id)  # NOT forced
    assert res2["confirmed"] and res2["session_status"] == "pushed"
    assert not _oracle(db, s, server, res2)
    assert len(server.named("milk")) == 1 and len(server.named("eggs")) == 1


def test_partial_failure_keeps_what_landed_and_retries_only_what_failed(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}, {"name": "eggs", "quantity": 6, "unit": None}])
    _need_all(db, s)
    server.post_rule = lambda n, op: "drop" if op["item"] and op["item"]["name"] == "Eggs" else None
    res = cl.push_to_anylist(db, s.id)
    assert res["failed"] == ["Eggs"] and res["added"] == ["Milk"]

    server.post_rule = None
    res2 = cl.push_to_anylist(db, s.id)
    assert res2["already_active"] == ["Milk"] and res2["added"] == ["Eggs"] and res2["confirmed"]
    assert not _oracle(db, s, server, res2)


def test_a_stale_row_id_after_the_item_was_deleted_on_the_phone_is_re_added(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    cl.push_to_anylist(db, s.id)
    server.phone_delete("milk")  # no reload: the row still holds the old id
    res = cl.push_to_anylist(db, s.id, force=True)
    assert res["added"] == ["Milk"] and not _oracle(db, s, server, res)


def test_two_rows_with_the_same_display_name_are_reported_by_row_not_by_name(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}, {"name": "salt", "quantity": 1, "unit": "tsp"}])
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id, progress_token="tok-keys")
    keys = [it["key"] for it in res["items"]]
    assert len(set(keys)) == len(keys) == 2 and all(k.startswith("item:") for k in keys)


# --- usuals -----------------------------------------------------------------------------------


def _due_usual(db, name):
    return usuals_service.create_usual(db, UsualItemCreate(name=name, cadence_days=7))


def test_a_ticked_usual_already_on_the_list_is_not_duplicated_and_a_crossed_off_one_is_uncrossed(db, server):
    active = server.phone_add("Bog Roll")
    crossed = server.phone_add("Coffee Bean", checked=True)
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    u1, u2 = _due_usual(db, "bog roll"), _due_usual(db, "coffee beans")
    res = cl.push_to_anylist(db, s.id, usual_ids=[u1.id, u2.id])
    outcomes = {i["key"]: i["outcome"] for i in res["items"]}
    assert outcomes[f"usual:{u1.id}"] == "already-active" and outcomes[f"usual:{u2.id}"] == "un-crossed"
    assert server.items[crossed]["checked"] is False and server.items[active]["checked"] is False
    assert len(server.named("bog roll")) == 1
    assert sorted(res["usuals_added"]) == ["bog roll", "coffee bean"]


def test_a_usual_that_is_also_an_ingredient_line_is_pushed_once(db, server):
    s = _session(db, [{"name": "salt", "quantity": 1, "unit": "tsp"}])
    _need_all(db, s)
    usual = _due_usual(db, "salt")
    res = cl.push_to_anylist(db, s.id, usual_ids=[usual.id])
    assert len(server.named("salt")) == 1
    covered = next(i for i in res["items"] if i["key"] == f"usual:{usual.id}")
    assert covered["outcome"] == "already-active" and "covered" in covered["reason"]
    assert res["usuals_added"] == ["salt"]


# --- history / diagnostics / API shape ---------------------------------------------------------


def test_history_records_every_item_result_under_the_push_id(db, server):
    server.phone_add("Milk", "1 L", checked=True)
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}, {"name": "eggs", "quantity": 6, "unit": None}])
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id)
    row = db.get(ShoppingHistory, res["history_id"])
    payload = json.loads(row.anylist_response_json)
    assert payload["push_id"] == res["push_id"] and payload["discrepancies"] == []
    assert {i["outcome"] for i in payload["items"]} == {"un-crossed", "added"}
    assert set(payload["timings"]) >= {"read", "send", "confirm"}
    assert json.loads(row.items_json)["push_id"] == res["push_id"]


def test_the_unconfirmed_history_row_names_the_failed_lines(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    server.post_rule = lambda n, op: "drop"
    res = cl.push_to_anylist(db, s.id)
    payload = json.loads(db.get(ShoppingHistory, res["history_id"]).anylist_response_json)
    assert payload["discrepancies"] and "Milk" in payload["discrepancies"][0]
    assert payload["items"][0]["outcome"] == "failed" and payload["items"][0]["reason"]


def test_progress_stages_run_reading_sending_confirming_done(db, server, monkeypatch):
    seen = []
    real = progress_tracker.set_stage
    monkeypatch.setattr(progress_tracker, "set_stage", lambda t, st: (seen.append(st), real(t, st)))
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    cl.push_to_anylist(db, s.id, progress_token="tok-stages")
    deduped = [x for i, x in enumerate(seen) if i == 0 or seen[i - 1] != x]
    assert deduped == ["reading", "sending", "confirming", "done"]


def test_unreadable_list_before_anything_changes_raises_and_writes_nothing(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    server.get_rule = lambda n: ("status", 500)
    with pytest.raises(ac.AnyListError):
        cl.push_to_anylist(db, s.id)
    assert server.posts == [] and sessions_service.get_session(db, s.id).status != "pushed"


# --- the seeded fuzz --------------------------------------------------------------------------

VOCAB = [  # (name as in a recipe, quantity, unit)
    ("milk", 1, "l"), ("egg", 6, None), ("tomato", 4, None), ("beef mince", 500, "g"),
    ("red capsicum", 2, None), ("olive oil", 2, "tbsp"), ("salt", 1, "tsp"), ("parmesan", 35, "g"),
    ("spring onion", 1, "bunch"), ("black bean", 400, "g"),
]
PHONE_NAMES = ["Milk", "Eggs", "Tomatoes", "Beef Mince", "Red Capsicums", "Olive Oil", "Salt", "Parmesan"]
FAULTS = [None, "drop-first", "timeout-first", "500-first", "stale-readback", "drop-all"]


def _line_problem(r, before) -> bool:
    """True when this Need-it row is NOT correctly on the list right now."""
    active = _active_matches(r, ac.get_items())
    want = (cl._anylist_quantity(r) or "").strip().casefold()
    limit = max(1, before.get(r.id, 0))
    return (not active or len(active) > limit
            or not any((a.quantity or "").strip().casefold() == want for a in active))


def _fuzz_one(seed: int, monkeypatch):
    rng = random.Random(seed)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    server = FakeAnyListServer()
    server.install(monkeypatch)
    try:
        for name in rng.sample(PHONE_NAMES, rng.randint(0, 4)):
            server.phone_add(name, rng.choice([None, "2", "1 L", "300 g"]), checked=rng.random() < 0.4)
        picks = rng.sample(VOCAB, rng.randint(2, 6))
        s = _session(db, [{"name": n, "quantity": q, "unit": u} for n, q, u in picks])
        log = []
        for _step in range(rng.randint(4, 9)):
            op = rng.choice(["need", "need", "phone", "alias", "push", "push", "reload"])
            rows = list(_rows(db, s).values())
            if op == "need" and rows:
                for r in rng.sample(rows, rng.randint(1, len(rows))):
                    cl.update_item(db, s.id, r.id, have_it="no", add_to_list=True)
            elif op == "phone":
                action = rng.choice(["cross", "delete", "rename", "dup", "add"])
                name = rng.choice(PHONE_NAMES)
                if action == "cross":
                    server.phone_cross_off(name)
                elif action == "delete":
                    server.phone_delete(name)
                elif action == "rename":
                    server.phone_rename(name, name + " Fresh")
                elif action == "dup":
                    server.phone_add(name, "1")
                else:
                    server.phone_add(name, rng.choice([None, "5"]), checked=rng.random() < 0.5)
                log.append(f"phone:{action}:{name}")
            elif op == "alias" and len(rows) >= 2:
                a, b = rng.sample([r.ingredient_name for r in rows], 2)
                try:
                    aliases_service.create_alias(db, IngredientAliasCreate(alias_name=a, canonical_name=b))
                except Exception:  # noqa: BLE001 — a duplicate alias etc. is just a no-op step
                    pass
                sessions_service.consolidate_session(db, s.id)
                log.append(f"alias:{a}->{b}")
            elif op == "reload":
                cl.load_checklist(db, s.id)
            elif op == "push":
                fault = rng.choice(FAULTS)
                server.post_rule = server.get_rule = None
                if fault == "drop-first":
                    server.post_rule = lambda n, o: "drop" if n == 1 else None
                elif fault == "timeout-first":
                    server.post_rule = lambda n, o: "timeout" if n == 1 else None
                elif fault == "500-first":
                    server.post_rule = lambda n, o: ("status", 500) if n == 1 else None
                elif fault == "stale-readback":
                    server.get_rule = lambda n: "stale" if n == 2 else None
                elif fault == "drop-all":
                    server.post_rule = lambda n, o: "drop"
                cl.load_checklist(db, s.id) if rng.random() < 0.5 else None
                log.append(f"push:{fault}")
                before = {r.id: len(_active_matches(r, ac.get_items())) for r in _need_rows(db, s)}
                res = cl.push_to_anylist(db, s.id, force=True)
                problems = _oracle(db, s, server, res, before)
                ok_keys = {i["key"] for i in res["items"] if i["outcome"] != "failed"}
                for r in _need_rows(db, s):
                    if f"item:{r.id}" in ok_keys and _line_problem(r, before):
                        problems.append(f"{r.ingredient_name!r}: reported OK but the list disagrees")
                if res["confirmed"]:
                    assert not problems, (seed, log, problems)
                    if fault in (None, "stale-readback"):  # idempotence: nothing changed -> nothing written
                        server.post_rule = server.get_rule = None
                        before = len(server.posts)
                        again = cl.push_to_anylist(db, s.id, force=True)
                        assert again["confirmed"] and not (again["added"] or again["updated"]), (seed, log, again["items"])
                        assert len(server.posts) == before, (seed, log, "a no-change re-push wrote something")
                else:
                    # not confirmed: every line that is NOT satisfied must be named as failed
                    failed = {i["key"] for i in res["items"] if i["outcome"] == "failed"}
                    for r in _need_rows(db, s):
                        if _line_problem(r, before) and f"item:{r.id}" not in failed:
                            raise AssertionError((seed, log, f"SILENT: {r.ingredient_name!r} is not on the list and not reported failed"))
    finally:
        db.close()
        engine.dispose()
        ac.reset_client()


@pytest.mark.parametrize("seed_block", range(6))
def test_fuzz_push_sequences(monkeypatch, seed_block):
    """Hundreds of random user/phone/fault sequences (fixed seeds, so any failure replays)."""
    for seed in range(seed_block * 40, seed_block * 40 + 40):
        monkeypatch.undo()
        _fuzz_one(seed, monkeypatch)


# --- remaining branches of the push path (coverage pass) ---------------------------------------


def test_load_with_an_unreachable_anylist_keeps_state_and_reports_it(db, server):
    server.phone_add("Milk", "1 L")
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    cl.load_checklist(db, s.id)
    assert _rows(db, s)["milk"].already_on_anylist is True
    server.get_rule = lambda n: ("status", 500)
    items, ok, detail, _b = cl.load_checklist(db, s.id)
    assert ok is False and detail
    assert items[0].already_on_anylist is True  # a transient failure must not wipe a good match


def test_merge_upgrades_the_surviving_row_to_the_strongest_decision(db, server):
    s = _session(db, [{"name": "beef mince", "quantity": 500, "unit": "g"},
                      {"name": "minced beef", "quantity": 200, "unit": "g"}])
    rows = _rows(db, s)
    cl.update_item(db, s.id, rows["beef mince"].id, have_it="unknown")
    cl.update_item(db, s.id, rows["minced beef"].id, have_it="no", add_to_list=True)
    cl.merge_items(db, s.id, item_names=["beef mince", "minced beef"], canonical_name="beef mince", remember=False)
    survivor = _rows(db, s)["beef mince"]
    assert (survivor.have_it, survivor.add_to_list) == ("no", True)


def test_every_pre_push_edit_is_refused_once_the_session_is_pushed(db, server):
    s = _session(db, [{"name": "milk", "quantity": 1, "unit": "l"}])
    _need_all(db, s)
    cl.push_to_anylist(db, s.id)
    item_id = _rows(db, s)["milk"].id
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.substitute_item(db, s.id, item_id, substitute_name="oat milk", original_qty=None, original_unit=None,
                           substitute_qty=None, substitute_unit=None, remember=False)
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.alias_item(db, s.id, item_id, alias_name="full cream milk", remember=False)
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.pack_size_item(db, s.id, item_id, purchase_label="2 L carton", purchase_qty=2, purchase_unit="l", remember=False)
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.coarse_item(db, s.id, item_id, purchase_label=None, recipes_per_pack=2, remember=False)
    with pytest.raises(cl.SessionAlreadyPushedError):
        cl.merge_items(db, s.id, item_names=["milk"], canonical_name="milk", remember=False)


# --- names pushed to AnyList (Chunk 6.7 naming rule) ---------------------------------------------


def test_names_pushed_use_the_households_wording_and_correct_capitalisation(db, server):
    s = _session(db, [
        {"name": "black beans", "quantity": 800, "unit": "g"},
        {"name": "salt", "quantity": 2, "unit": "tsp"},
        {"name": "vegetable oil", "quantity": 4, "unit": "tbsp"},
        {"name": "cheddar cheese or monterey jack", "quantity": 200, "unit": "g"},
        {"name": "baker's chocolate", "quantity": 100, "unit": "g"},
    ])
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id)
    pushed = {i["name"] for i in res["items"]}
    assert pushed == {"Black Beans", "Salt", "Vegetable Oil", "Cheddar Cheese or Monterey Jack", "Baker's Chocolate"}
    assert res["confirmed"] and not _oracle(db, s, server, res)


def test_items_pushed_earlier_under_old_spellings_are_still_found_not_duplicated(db, server):
    # what the old display logic left on the list: "Salts", "Vegetable Oils", "Black Bean"
    old = {n: server.phone_add(n, q) for n, q in (("Salts", "2 tsp"), ("Vegetable Oils", "4 tbsp"), ("Black Bean", "800 g"))}
    s = _session(db, [{"name": "black beans", "quantity": 800, "unit": "g"},
                      {"name": "salt", "quantity": 2, "unit": "tsp"},
                      {"name": "vegetable oil", "quantity": 4, "unit": "tbsp"}])
    items, _ok, _d, _b = cl.load_checklist(db, s.id)
    assert all(i.already_on_anylist for i in items)  # matched through the key, despite the old spellings
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id)
    assert sorted(i["outcome"] for i in res["items"]) == ["already-active"] * 3
    assert server.posts == [] and set(old.values()) == set(server.items)  # nothing added, nothing renamed


def test_a_replace_moves_an_old_spelling_to_the_new_name(db, server):
    server.phone_add("Black Bean", "400 g")
    s = _session(db, [{"name": "black beans", "quantity": 800, "unit": "g"}])
    _need_all(db, s)
    res = cl.push_to_anylist(db, s.id)
    assert res["updated"] == ["Black Beans"] and res["confirmed"]
    assert [i["name"] for i in server.items.values()] == ["Black Beans"]

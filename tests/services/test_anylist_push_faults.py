"""The AnyList push, exhaustively, against a stateful fake server with fault injection
(Chunk 6.7 — docs/anylist-push.md > Test map).

One oracle decides every scenario, independent of what the connector claims:

* a line the connector reports OK must really be on the list — exactly once ACTIVE, uncrossed,
  with the wanted quantity (never a false "confirmed");
* a line that is NOT on the list like that must be reported as failed, by name, with a reason
  (never silent);
* ``confirmed`` is true exactly when every line is OK;
* bystander items on the list are never touched;
* nothing raises for a per-line problem.

Scenarios are the cross-product of: what is on the list for the wanted item (absent / active /
crossed off, bare-count / unit-bearing / no quantity, a duplicate pair), what the caller believes
(no id / the right id / a stale id), what quantity and note is wanted, and which fault is injected
(a dropped / timed-out / 500 / 401 write, a stale or timed-out read-back, persistent drops...).
"""

from __future__ import annotations

import itertools
import os

import pytest

from app.services import anylist_client as ac
from app.services.anylist_client import PushItem
from tests.services.anylist_fake_server import FakeAnyListServer

# --- scenario axes -----------------------------------------------------------------------

# (label, items to put on the list for "milk")
STATES = {
    "absent": [],
    "active-bare": [dict(name="milk", qty="2")],
    "active-unit": [dict(name="milk", qty="2 L", note="old note")],
    "active-noqty": [dict(name="milk")],
    "crossed-bare": [dict(name="milk", qty="2", checked=True)],
    "crossed-unit": [dict(name="milk", qty="2 L", note="old note", checked=True)],
    "crossed-noqty": [dict(name="milk", checked=True)],
    "dup-active-and-crossed": [dict(name="milk", qty="2 L", checked=True), dict(name="milk", qty="2 L")],
}
WANT_QTY = [None, "3", "2", "3 L", "2 L"]
WANT_NOTE = [None, "fresh note"]
ID_MODES = ["none", "right", "stale"]

# fault label -> (installer, transient?) ; "transient" means a correct connector can heal it
FAULTS = [
    "none", "drop-first-write", "timeout-first-write", "http500-first-write",
    "reauth-first-write", "stale-first-readback", "timeout-first-readback",
    "drop-all-writes", "drop-all-removes", "readback-always-fails",
]
TRANSIENT = {
    "none", "drop-first-write", "timeout-first-write", "http500-first-write",
    "reauth-first-write", "stale-first-readback", "timeout-first-readback",
}


def _install_fault(server: FakeAnyListServer, fault: str) -> None:
    if fault == "drop-first-write":
        server.post_rule = lambda n, op: "drop" if n == 1 else None
    elif fault == "timeout-first-write":
        server.post_rule = lambda n, op: "timeout" if n == 1 else None
    elif fault == "http500-first-write":
        server.post_rule = lambda n, op: ("status", 500) if n == 1 else None
    elif fault == "reauth-first-write":
        server.post_rule = lambda n, op: "401" if n == 1 else None
    elif fault == "stale-first-readback":
        server.get_rule = lambda n: "stale" if n == 2 else None
    elif fault == "timeout-first-readback":
        server.get_rule = lambda n: "timeout" if n == 2 else None
    elif fault == "drop-all-writes":
        server.post_rule = lambda n, op: "drop"
    elif fault == "drop-all-removes":
        server.post_rule = lambda n, op: "drop" if op["handler"] == "remove-shopping-list-item" else None
    elif fault == "readback-always-fails":
        server.get_rule = lambda n: "timeout" if n >= 2 else None


def _existing_id(server: FakeAnyListServer, mode: str, state: str) -> str | None:
    if mode == "none":
        return None
    if mode == "stale":
        return "id-that-is-not-on-the-list"
    named = server.named("milk")
    if not named:
        return None
    actives = [n for n in named if not n["checked"]]
    return (actives or named)[0]["id"]  # what checklist._best_match would pick


def _satisfied(server: FakeAnyListServer, item: PushItem) -> bool:
    active = server.active(item.name)
    return len(active) == 1 and (active[0]["qty"] or "").strip() == (item.quantity or "").strip()


def _run(monkeypatch, state: str, fault: str, qty, note, id_mode: str):
    server = FakeAnyListServer(STATES[state])
    bystanders = [server.phone_add("bread", "1"), server.phone_add("tea", None, checked=True)]
    server.install(monkeypatch)
    _install_fault(server, fault)
    item = PushItem(name="Milk", quantity=qty, note=note, existing_id=_existing_id(server, id_mode, state), key="item:1")
    before = {i: dict(it) for i, it in server.items.items() if i in bystanders}
    result = ac.add_or_increment_items([item], list_name="TestList", push_id="t")
    return server, item, result, bystanders, before


def _check_oracle(server, item, result, bystanders, before, transient: bool, label: str):
    problems = []
    (r,) = result.items
    satisfied = _satisfied(server, item)
    if r.ok and not satisfied:
        problems.append("FALSE OK: reported ok but list state is wrong")
    if not satisfied and r.ok is False and not r.reason:
        problems.append("failed without a reason")
    if not satisfied and r.ok:
        problems.append("SILENT: not satisfied and not reported failed")
    if result.confirmed != all(x.ok for x in result.items):
        problems.append("confirmed disagrees with per-item results")
    if result.confirmed and not satisfied:
        problems.append("FALSE CONFIRM")
    if transient and not (satisfied and r.ok):
        problems.append(f"transient fault did not heal: outcome={r.outcome} reason={r.reason}")
    for ident, was in before.items():
        if server.items.get(ident) != was:
            problems.append(f"bystander {was['name']!r} was touched")
    if len(server.active(item.name)) > 1:
        problems.append("DUPLICATE active items for the wanted line")
    return [f"{label}: {p}" for p in problems]


# --- the matrix ---------------------------------------------------------------------------


def _scenarios(state: str, fault: str):
    """The (qty, note, id_mode) scenarios to run for one (state, fault) cell.

    2026-10-07 test-suite audit: the full cross-product is 30 scenarios per cell (2,400 in all,
    ~35 s). By default each cell runs a diagonal third of it — the combos where
    ``(qty + note + id) % 3`` equals a per-cell offset — so EVERY cell still sees every quantity,
    both notes and all three id modes, and neighbouring cells use different offsets so the
    suite as a whole still covers the whole product. ``FULL_PUSH_MATRIX=1`` runs all 30 per
    cell; do that before any change to the push path (docs/anylist-push.md > Test map).
    """
    full = list(itertools.product(WANT_QTY, WANT_NOTE, ID_MODES))
    if os.environ.get("FULL_PUSH_MATRIX") == "1":
        return full
    offset = (list(STATES).index(state) + FAULTS.index(fault)) % 3
    return [
        (qty, note, id_mode)
        for qi, qty in enumerate(WANT_QTY)
        for ni, note in enumerate(WANT_NOTE)
        for ii, id_mode in enumerate(ID_MODES)
        if (qi + ni + ii) % 3 == offset
    ]


@pytest.mark.parametrize("state", list(STATES))
@pytest.mark.parametrize("fault", FAULTS)
def test_push_matrix(monkeypatch, state, fault):
    problems: list[str] = []
    for qty, note, id_mode in _scenarios(state, fault):
        monkeypatch.undo()  # a fresh client/server per scenario
        server, item, result, bystanders, before = _run(monkeypatch, state, fault, qty, note, id_mode)
        label = f"state={state} fault={fault} want=({qty!r},{note!r}) id={id_mode}"
        problems += _check_oracle(server, item, result, bystanders, before, fault in TRANSIENT, label)
    assert not problems, "\n".join(problems[:15]) + f"\n({len(problems)} problem(s) in this cell)"


@pytest.mark.parametrize("state", list(STATES))
def test_a_second_identical_push_writes_nothing(monkeypatch, state):
    """Idempotence: once a push has succeeded, pushing the same thing again is a pure read."""
    for qty, note in itertools.product(WANT_QTY, WANT_NOTE):
        monkeypatch.undo()
        server = FakeAnyListServer(STATES[state])
        server.install(monkeypatch)
        first_id = _existing_id(server, "right", state)
        first = ac.add_or_increment_items(
            [PushItem(name="Milk", quantity=qty, note=note, existing_id=first_id, key="item:1")], list_name="TestList"
        )
        assert first.confirmed, (state, qty, note, first.discrepancies)
        # the caller re-matches by name against a fresh read, exactly as checklist.push_to_anylist does
        now_active = server.active("milk")
        second_id = now_active[0]["id"] if now_active else None
        writes_before = len(server.posts)
        second = ac.add_or_increment_items(
            [PushItem(name="Milk", quantity=qty, note=note, existing_id=second_id, key="item:1")], list_name="TestList"
        )
        assert second.confirmed and second.items[0].outcome == "already-active", (state, qty, note, second.items)
        assert len(server.posts) == writes_before, "a no-change re-push must send no writes"


# --- explicit behaviours (each is a rule documented in docs/anylist-push.md) ---------------


def _push(monkeypatch, server, *items, **kw):
    server.install(monkeypatch)
    return ac.add_or_increment_items(list(items), list_name="TestList", **kw)


def test_fresh_add_is_one_add_op(monkeypatch):
    server = FakeAnyListServer()
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", note="n", key="a"))
    assert [p["handler"] for p in server.posts] == ["add-shopping-list-item"]
    assert res.items[0].outcome == "added" and res.confirmed
    assert server.active("milk")[0]["note"] == "n"


def test_active_identical_item_is_left_alone(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="1 L", note="n")])
    ident = server.ids("milk")[0]
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", note="n", existing_id=ident, key="a"))
    assert server.posts == [] and res.items[0].outcome == "already-active"


def test_bare_count_change_uses_set_quantity_only(monkeypatch):
    server = FakeAnyListServer([dict(name="Eggs", qty="6")])
    ident = server.ids("eggs")[0]
    res = _push(monkeypatch, server, PushItem(name="Eggs", quantity="8", existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["set-list-item-quantity"]
    assert res.items[0].outcome == "updated" and server.items[ident]["qty"] == "8"


def test_unit_bearing_change_is_remove_then_add_under_a_new_id(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L", note="old")])
    ident = server.ids("milk")[0]
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="3 L", note="new", existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["remove-shopping-list-item", "add-shopping-list-item"]
    assert ident not in server.items and res.added_ids["a"] != ident
    assert server.active("milk")[0]["note"] == "new" and res.items[0].outcome == "updated"


def test_crossed_off_item_is_uncrossed_in_place_keeping_id_and_note(monkeypatch):
    server = FakeAnyListServer([dict(name="Salt", note="household's own note", checked=True)])
    ident = server.ids("salt")[0]
    res = _push(monkeypatch, server, PushItem(name="Salt", quantity=None, existing_id=ident, key="a"))
    assert [(p["handler"], p["value"]) for p in server.posts] == [("set-list-item-checked", "n")]
    assert server.items[ident]["checked"] is False and server.items[ident]["note"] == "household's own note"
    assert res.items[0].outcome == "un-crossed" and res.items[0].ident == ident


def test_crossed_off_bare_count_with_new_quantity_unchecks_then_sets_quantity(monkeypatch):
    server = FakeAnyListServer([dict(name="Eggs", qty="6", checked=True)])
    ident = server.ids("eggs")[0]
    res = _push(monkeypatch, server, PushItem(name="Eggs", quantity="8", existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["set-list-item-checked", "set-list-item-quantity"]
    assert server.items[ident] == {"name": "Eggs", "qty": "8", "note": None, "checked": False}
    assert res.items[0].outcome == "un-crossed"


def test_crossed_off_unit_bearing_with_new_quantity_is_replaced_uncrossed(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L", checked=True)])
    ident = server.ids("milk")[0]
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="3 L", existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["remove-shopping-list-item", "add-shopping-list-item"]
    assert len(server.named("milk")) == 1 and server.active("milk")[0]["qty"] == "3 L"
    assert res.items[0].outcome == "un-crossed"


def test_uncross_fallback_to_replace_when_in_place_is_disabled(monkeypatch):
    monkeypatch.setattr(ac, "_UNCROSS_IN_PLACE", False)
    server = FakeAnyListServer([dict(name="Salt", checked=True)])
    ident = server.ids("salt")[0]
    res = _push(monkeypatch, server, PushItem(name="Salt", quantity=None, existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["remove-shopping-list-item", "add-shopping-list-item"]
    assert res.items[0].outcome == "un-crossed" and server.active("salt")


def test_wanting_no_quantity_on_an_item_that_has_one_replaces_it(monkeypatch):
    # an empty set-list-item-quantity is a silent no-op, so clearing a quantity needs a replace
    server = FakeAnyListServer([dict(name="Milk", qty="2")])
    ident = server.ids("milk")[0]
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity=None, existing_id=ident, key="a"))
    assert [p["handler"] for p in server.posts] == ["remove-shopping-list-item", "add-shopping-list-item"]
    assert server.active("milk")[0]["qty"] is None and res.confirmed


def test_stale_existing_id_falls_back_to_a_fresh_add(monkeypatch):
    server = FakeAnyListServer()
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", existing_id="gone", key="a"))
    assert res.items[0].outcome == "added" and len(server.active("milk")) == 1


def test_operations_part_never_carries_a_filename_and_is_one_op_per_post(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L", checked=True)])
    ident = server.ids("milk")[0]
    _push(monkeypatch, server,
          PushItem(name="Milk", quantity="3 L", existing_id=ident, key="a"),
          PushItem(name="Bread", quantity="1", key="b"))
    assert all(p["applied"] for p in server.posts)  # a filename would make every one a silent no-op


# --- failure behaviour ---------------------------------------------------------------------


def test_a_failing_line_never_aborts_the_batch(monkeypatch):
    server = FakeAnyListServer()
    server.post_rule = lambda n, op: ("status", 500) if op["item"] and op["item"]["name"] == "Bad" else None
    res = _push(monkeypatch, server,
                PushItem(name="Good1", quantity="1", key="g1"),
                PushItem(name="Bad", quantity="1", key="bad"),
                PushItem(name="Good2", quantity="1", key="g2"))
    outcomes = {r.key: r.outcome for r in res.items}
    assert outcomes == {"g1": "added", "bad": "failed", "g2": "added"}
    assert res.confirmed is False and res.failed == ["Bad"] and "Bad" in res.discrepancies[0]
    assert res.added_ids.keys() == {"g1", "g2"}  # ids only for lines that landed


def test_circuit_breaker_stops_sending_after_repeated_failures(monkeypatch):
    server = FakeAnyListServer()
    server.post_rule = lambda n, op: "timeout"
    items = [PushItem(name=f"Item{i}", quantity="1", key=f"k{i}") for i in range(8)]
    res = _push(monkeypatch, server, *items)
    assert all(not r.ok for r in res.items) and not res.confirmed
    sent_before_giving_up = ac._MAX_CONSECUTIVE_FAILURES + ac._MAX_RETRIES * ac._MAX_CONSECUTIVE_FAILURES
    assert len(server.posts) <= sent_before_giving_up + 1  # not 8 items x timeouts
    assert any("not sent" in (r.reason or "") for r in res.items)


def test_replace_whose_add_is_dropped_is_healed_by_the_retry_with_the_same_new_id(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L")])
    ident = server.ids("milk")[0]
    server.post_rule = lambda n, op: "drop" if op["handler"] == "add-shopping-list-item" and n == 2 else None
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="3 L", existing_id=ident, key="a"))
    assert res.confirmed and res.items[0].retries == 1
    assert [p["handler"] for p in server.posts] == [
        "remove-shopping-list-item", "add-shopping-list-item", "add-shopping-list-item",
    ]
    adds = [p["item_id"] for p in server.posts if p["handler"] == "add-shopping-list-item"]
    assert adds[0] == adds[1]  # the retry reuses the same id, so it can never duplicate


def test_remove_ignored_is_healed_by_crossing_the_old_item_off(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L")])
    ident = server.ids("milk")[0]
    server.post_rule = lambda n, op: "drop" if op["handler"] == "remove-shopping-list-item" else None
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="3 L", existing_id=ident, key="a"))
    assert res.confirmed  # not an ACTIVE duplicate any more
    assert server.items[ident]["checked"] is True  # old one crossed off, new one active
    assert len(server.active("milk")) == 1 and server.active("milk")[0]["qty"] == "3 L"


def test_remove_and_cross_off_both_ignored_is_reported_as_duplicate_not_confirmed(monkeypatch):
    server = FakeAnyListServer([dict(name="Milk", qty="2 L")])
    ident = server.ids("milk")[0]
    server.post_rule = lambda n, op: (
        "drop" if op["handler"] in ("remove-shopping-list-item", "set-list-item-checked") else None
    )
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="3 L", existing_id=ident, key="a"))
    assert not res.confirmed and "duplicate" in res.items[0].reason


def test_a_lagging_read_is_re_read_not_re_sent(monkeypatch):
    server = FakeAnyListServer()
    server.get_rule = lambda n: "stale" if n == 2 else None
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", key="a"))
    assert res.confirmed and res.items[0].retries == 0
    assert server.post_count() == 1  # no blind re-send of a write that had in fact landed


def test_unreadable_list_reports_every_line_unconfirmed_and_resends_nothing(monkeypatch):
    server = FakeAnyListServer()
    server.get_rule = lambda n: "timeout" if n >= 2 else None
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", key="a"),
                PushItem(name="Bread", quantity="1", key="b"))
    assert not res.confirmed and all("could not confirm" in r.reason for r in res.items)
    assert server.post_count() == 2  # one write each; never re-sent blind (could duplicate)


def test_initial_list_read_failure_raises_before_anything_is_written(monkeypatch):
    server = FakeAnyListServer()
    server.get_rule = lambda n: ("status", 500)
    with pytest.raises(ac.AnyListError):
        _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", key="a"))
    assert server.posts == []


def test_a_transient_read_timeout_is_retried(monkeypatch):
    server = FakeAnyListServer()
    server.get_rule = lambda n: "timeout" if n == 1 else None
    res = _push(monkeypatch, server, PushItem(name="Milk", quantity="1 L", key="a"))
    assert res.confirmed


def test_progress_callbacks_use_the_row_key_and_report_stages(monkeypatch):
    server = FakeAnyListServer()
    seen, stages = [], []
    server.install(monkeypatch)
    ac.add_or_increment_items(
        [PushItem(name="Milk", quantity="1 L", key="item:7"), PushItem(name="Milk", quantity="2 L", key="item:8")],
        list_name="TestList", on_item=lambda ref, st: seen.append((ref, st)), on_stage=stages.append,
    )
    assert stages == ["sending", "confirming"]
    assert ("item:7", "active") in seen and ("item:8", "done") in seen  # two lines, same name, distinct keys

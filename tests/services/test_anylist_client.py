"""Unit tests for app/services/anylist_client.py — Phase 5 Chunk 5.2, extended at Chunk 5.7's
live-verification fix (2026-09-12).

No network: fake mode, a hand-built protobuf blob for the read path, and httpx.MockTransport
for the real client. The spike findings baked into the connector (two quantity fields,
no-filename multipart part, re-fetch-and-diff confirmation) are each exercised, plus the
Chunk 5.7 findings: one operation per HTTP request (never batched across items), and
`set-list-item-details` syncing a note on the update path.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import anylist_client as ac
from app.services.anylist_client import (
    AnyListDisabledError,
    AnyListError,
    PushItem,
    _build_operation_list,
    _decode_message,
    _field_message,
    _field_string,
    _item_from_wire,
    _item_to_wire,
    _parse_user_data,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    ac.reset_client()
    yield
    ac.reset_client()


def _fake_mode(monkeypatch):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", True, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_enabled", False, raising=False)


# --- wire codec ---------------------------------------------------------------


def test_item_wire_roundtrips_name_and_quantity():
    raw = _item_to_wire(identifier="abc123", list_id="L1", name="Beef Mince", quantity="500g")
    item = _item_from_wire(raw)
    assert item.identifier == "abc123"
    assert item.name == "Beef Mince"
    assert item.quantity == "500g"
    assert item.checked is False


def test_item_wire_roundtrips_details():
    raw = _item_to_wire(
        identifier="abc123", list_id="L1", name="Passata", quantity="400g", details="to taste"
    )
    fields = _decode_message(raw)
    assert fields[5][0].decode("utf-8") == "to taste"
    # AnyListItem.note (added Chunk 5.7) -- previously this type had no way to represent the
    # details field at all, which is part of why the update-path note bug went undetected.
    assert _item_from_wire(raw).note == "to taste"


def test_item_from_wire_reads_legacy_deprecated_quantity_field_18():
    # An item whose quantity was updated via set-list-item-quantity carries field 18, not 21.
    raw = _field_string(1, "id1") + _field_string(4, "Milk") + _field_string(18, "2 x 2L")
    item = _item_from_wire(raw)
    assert item.quantity == "2 x 2L"  # spike finding #1


def test_item_from_wire_prefers_field_21_over_18():
    raw = (
        _field_string(1, "id1")
        + _field_string(4, "Milk")
        + _field_string(18, "legacy")
        + _field_message(21, _field_string(1, "modern"))
    )
    assert _item_from_wire(raw).quantity == "modern"


def test_parse_user_data_walks_the_nesting():
    item = _item_to_wire(identifier="i1", list_id="L1", name="Eggs", quantity="1 dozen")
    wire_list = _field_string(1, "L1") + _field_string(3, "TestList") + _field_message(4, item)
    inner = _field_message(1, wire_list)          # ShoppingListsResponse.newLists
    top = _field_message(1, inner)                # PBUserDataResponse.shoppingListsResponse
    lists = _parse_user_data(top)
    assert [l.name for l in lists] == ["TestList"]
    assert lists[0].items[0].name == "Eggs" and lists[0].items[0].quantity == "1 dozen"


def test_operation_list_is_length_delimited_field_1_repeated():
    body = _build_operation_list([b"\x01\x02", b"\x03"])
    decoded = _decode_message(body)
    assert [bytes(v) for v in decoded[1]] == [b"\x01\x02", b"\x03"]


# --- gate -------------------------------------------------------------------


def test_disabled_gate_raises(monkeypatch):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_enabled", False, raising=False)
    with pytest.raises(AnyListDisabledError):
        ac.get_items("TestList")


# --- fake mode ------------------------------------------------------------


def test_fake_mode_seeds_the_target_list(monkeypatch):
    _fake_mode(monkeypatch)
    monkeypatch.setattr(ac.settings, "anylist_target_list_name", "TestList", raising=False)
    names = {i.name for i in ac.get_items()}
    assert {"milk", "eggs", "butter"} <= names


def test_fake_mode_add_and_update(monkeypatch):
    _fake_mode(monkeypatch)
    monkeypatch.setattr(ac.settings, "anylist_target_list_name", "TestList", raising=False)
    existing = next(i for i in ac.get_items() if i.name == "milk")

    res = ac.add_or_increment_items(
        [
            PushItem(name="passata", quantity="400g", note="to taste"),
            PushItem(name="milk", quantity="3 x 2L", existing_id=existing.identifier, note="new note"),
        ]
    )
    assert res.added == ["passata"] and res.updated == ["milk"]
    assert res.confirmed is True

    now = {i.name: i for i in ac.get_items()}
    assert now["passata"].quantity == "400g"
    assert now["passata"].note == "to taste"  # a note lands correctly on add
    assert now["milk"].quantity == "3 x 2L"  # updated in place, no duplicate
    # Chunk 5.7: an update deliberately does NOT touch the note — see the module docstring's
    # set-list-item-details finding (doing so permanently breaks that item's quantity on the
    # real API). Fake mode mirrors this real limitation rather than an idealised behaviour.
    assert now["milk"].note is None
    assert sum(1 for i in ac.get_items() if i.name == "milk") == 1


# --- real client over a mock transport ----------------------------------


def _real_client(monkeypatch, handler):
    monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_enabled", True, raising=False)
    monkeypatch.setattr(ac.settings, "anylist_email", "user@example.com", raising=False)
    monkeypatch.setattr(ac.settings, "anylist_password", "pw", raising=False)
    monkeypatch.setattr(ac.settings, "anylist_target_list_name", "TestList", raising=False)
    client = ac._RealAnyList("user@example.com", "pw")
    client._http = httpx.Client(base_url=ac.BASE_URL, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ac, "_instance", client, raising=False)
    return client


def _added_items_from_multipart(body: bytes):
    """Pull (identifier, name, quantity) for each add op out of a shopping-lists/update
    multipart body — lets the mock server reflect back exactly what the client sent."""
    marker = b'name="operations"'
    i = body.index(marker)
    start = body.index(b"\r\n\r\n", i) + 4
    end = body.index(b"\r\n--", start)
    op_list = _decode_message(body[start:end])
    out = []
    for op in op_list.get(1, []):
        fields = _decode_message(bytes(op))
        if 6 not in fields:  # not an add (e.g. a set-list-item-quantity op)
            continue
        item = _decode_message(bytes(fields[6][0]))
        qty = None
        if 21 in item:
            qty = _decode_message(bytes(item[21][0])).get(1, [b""])[0].decode() or None
        out.append((item[1][0].decode(), item[4][0].decode(), qty))
    return out


def _operations_from_multipart(body: bytes):
    """(handler_id, list_item_id) for every operation in a shopping-lists/update multipart
    body, in submitted order — used to check op *sequencing* (e.g. add followed by a chained
    set-list-item-quantity), unlike _added_items_from_multipart which only looks at adds."""
    marker = b'name="operations"'
    i = body.index(marker)
    start = body.index(b"\r\n\r\n", i) + 4
    end = body.index(b"\r\n--", start)
    op_list = _decode_message(body[start:end])
    out = []
    for op in op_list.get(1, []):
        fields = _decode_message(bytes(op))
        metadata = _decode_message(bytes(fields[1][0]))
        handler_id = metadata[2][0].decode("utf-8")
        list_item_id = fields[3][0].decode("utf-8")
        out.append((handler_id, list_item_id))
    return out


def _updated_value_from_multipart(body: bytes) -> str:
    """The `updatedValue` (field 4) of the single operation in a shopping-lists/update
    multipart body -- for a set-list-item-quantity / set-list-item-details op."""
    marker = b'name="operations"'
    i = body.index(marker)
    start = body.index(b"\r\n\r\n", i) + 4
    end = body.index(b"\r\n--", start)
    op_list = _decode_message(body[start:end])
    op = _decode_message(bytes(op_list[1][0]))
    return op.get(4, [b""])[0].decode("utf-8")


def _user_data_bytes(items):
    """items: (ident, name, qty) or (ident, name, qty, note) tuples."""
    parts = b""
    for spec in items:
        ident, name, qty = spec[0], spec[1], spec[2]
        note = spec[3] if len(spec) > 3 else None
        parts += _field_message(
            4, _item_to_wire(identifier=ident, list_id="L1", name=name, quantity=qty, details=note)
        )
    wire_list = _field_string(1, "L1") + _field_string(3, "TestList") + parts
    return _field_message(1, _field_message(1, wire_list))


def test_real_get_items_authenticates_then_reads(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            assert request.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, content=_user_data_bytes([("i1", "Milk", "2L")]))
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    items = ac.get_items("TestList")
    assert [i.name for i in items] == ["Milk"]
    assert calls == ["/auth/token", "/data/user-data/get"]


def test_real_client_reauthenticates_once_on_401(monkeypatch):
    state = {"logins": 0, "gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            state["logins"] += 1
            return httpx.Response(200, json={"access_token": f"tok{state['logins']}"})
        state["gets"] += 1
        if state["gets"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, content=_user_data_bytes([("i1", "Milk", "2L")]))

    _real_client(monkeypatch, handler)
    items = ac.get_items("TestList")
    assert [i.name for i in items] == ["Milk"]
    assert state["logins"] == 2  # initial + one re-auth


def test_real_push_confirms_by_refetch_and_flags_a_silent_noop(monkeypatch):
    # Spike finding #3: HTTP 200 but the add didn't land -> confirmed False, discrepancy.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes([]))  # list stays empty
        if request.url.path == "/data/shopping-lists/update":
            # the operations part must carry no filename (spike finding #2)
            assert b'filename="' not in request.content
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items([PushItem(name="passata", quantity="400g")], list_name="TestList")
    assert res.added == ["passata"]
    assert res.confirmed is False
    assert res.discrepancies and "did not land" in res.discrepancies[0]


def test_real_push_confirms_when_the_item_shows_up(monkeypatch):
    added = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes(added))
        if request.url.path == "/data/shopping-lists/update":
            added.extend(_added_items_from_multipart(request.content))  # server accepts them
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items([PushItem(name="passata", quantity="400g")], list_name="TestList")
    assert res.confirmed is True and not res.discrepancies


def test_real_add_embeds_quantity_alone_no_chained_set_op(monkeypatch):
    # Chunk 5.7 live-verification (2026-09-12) supersedes a 2026-09-10 finding that used to be
    # tested here ("add must chain a set-list-item-quantity op or the quantity won't show").
    # That finding was a misdiagnosis of the "one op per request" bug below — confirmed live,
    # quantity embedded only in the add's own item message (field 21) renders correctly with
    # NO follow-up op, matching the reference codetheweb/anylist client's own _encode().
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes(captured.get("added", [])))
        if request.url.path == "/data/shopping-lists/update":
            ops = _operations_from_multipart(request.content)
            captured.setdefault("posts", []).append(ops)
            new_id = ops[0][1]
            captured["added"] = [(new_id, "Passata", "400g")]  # reflect the add so it confirms
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items([PushItem(name="Passata", quantity="400g")], list_name="TestList")

    assert len(captured["posts"]) == 1  # exactly one POST for one item
    assert [h for h, _ in captured["posts"][0]] == ["add-shopping-list-item"]
    assert res.confirmed is True


def test_real_multi_item_push_sends_one_operation_per_post(monkeypatch):
    """The Chunk 5.7 fix's core discipline: AnyList's server silently drops an operation when
    a request's operation list touches more than one distinct item — confirmed live. Each
    item's op(s) must go out in its own separate POST, never batched with another item's."""
    captured = {"posts": [], "added": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes(captured["added"]))
        if request.url.path == "/data/shopping-lists/update":
            ops = _operations_from_multipart(request.content)
            captured["posts"].append(ops)
            for handler_id, item_id in ops:
                if handler_id == "add-shopping-list-item":
                    name = "Passata" if len(captured["posts"]) == 1 else "Saffron"
                    qty = "400g" if name == "Passata" else None
                    captured["added"].append((item_id, name, qty))
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items(
        [PushItem(name="Passata", quantity="400g"), PushItem(name="Saffron", quantity=None)],
        list_name="TestList",
    )

    assert len(captured["posts"]) == 2  # one POST per item, never combined
    assert all(len(ops) == 1 for ops in captured["posts"])  # exactly one op each
    assert res.confirmed is True


def test_real_update_sends_only_quantity_never_details(monkeypatch):
    """Chunk 5.7 live-verification found a second, nastier bug behind a first attempt to fix
    the stale-note-on-update issue: once set-list-item-details touches an item, every later
    set-list-item-quantity op for that SAME item silently fails (confirmed reproducible —
    field 21 AND the legacy field 18 both come back completely absent, not stale). Reverted:
    the update path sends ONLY set-list-item-quantity, one POST, and does not attempt to sync
    the note at all -- an accepted, documented limitation (see the module docstring), not an
    oversight. A note still lands correctly on an item's first ADD (untouched by this)."""
    captured = {"posts": [], "quantity": "2L"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(
                200, content=_user_data_bytes([("existing1", "Milk", captured["quantity"], "old note")])
            )
        if request.url.path == "/data/shopping-lists/update":
            ops = _operations_from_multipart(request.content)
            captured["posts"].append(ops)
            handler_id, _ = ops[0]
            if handler_id == "set-list-item-quantity":
                captured["quantity"] = _updated_value_from_multipart(request.content)
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items(
        [PushItem(name="Milk", quantity="3L", existing_id="existing1", note="new note")],
        list_name="TestList",
    )

    assert len(captured["posts"]) == 1  # quantity only, never a details op too
    assert [ops[0][0] for ops in captured["posts"]] == ["set-list-item-quantity"]
    assert captured["quantity"] == "3L"
    assert res.confirmed is True
    assert res.updated == ["Milk"]


def test_real_get_items_unknown_list_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, content=_user_data_bytes([("i1", "Milk", "2L")]))

    _real_client(monkeypatch, handler)
    with pytest.raises(AnyListError):
        ac.get_items("NoSuchList")

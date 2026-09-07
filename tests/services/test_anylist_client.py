"""Unit tests for app/services/anylist_client.py — Phase 5 Chunk 5.2.

No network: fake mode, a hand-built protobuf blob for the read path, and httpx.MockTransport
for the real client. The three spike findings baked into the connector (two quantity fields,
no-filename multipart part, re-fetch-and-diff confirmation) are each exercised.
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
            PushItem(name="passata", quantity="400g"),
            PushItem(name="milk", quantity="3 x 2L", existing_id=existing.identifier),
        ]
    )
    assert res.added == ["passata"] and res.updated == ["milk"]
    assert res.confirmed is True

    now = {i.name: i for i in ac.get_items()}
    assert now["passata"].quantity == "400g"
    assert now["milk"].quantity == "3 x 2L"  # updated in place, no duplicate
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


def _user_data_bytes(items):
    parts = b""
    for ident, name, qty in items:
        parts += _field_message(
            4, _item_to_wire(identifier=ident, list_id="L1", name=name, quantity=qty)
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


def test_real_get_items_unknown_list_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, content=_user_data_bytes([("i1", "Milk", "2L")]))

    _real_client(monkeypatch, handler)
    with pytest.raises(AnyListError):
        ac.get_items("NoSuchList")

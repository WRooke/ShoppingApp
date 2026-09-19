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


def test_item_to_wire_splits_unit_bearing_quantity_into_rawquantity_amount_unit():
    """2026-09-20 fix (fault-finding spike "Stage 1" addendum, PR #62 on the reference library,
    never merged upstream): AnyList's own app was live-phone-confirmed to show "Not set" for a
    freshly-added item whose quantityPb carried only `amount` = "500 g" (non-numeric, no
    `rawQuantity`) -- and to display correctly once `rawQuantity` is set properly, split the
    PR #62 way. `_item_to_wire` must set all three sub-fields now, not just the whole string
    crammed into `amount` alone."""
    raw = _item_to_wire(identifier="i1", list_id="L1", name="Beef Mince", quantity="500 g")
    qty_pb = _decode_message(_decode_message(raw)[21][0])
    assert qty_pb[3][0].decode("utf-8") == "500 g"  # rawQuantity: the exact text
    assert qty_pb[1][0].decode("utf-8") == "500"    # amount: the parsed leading number
    assert qty_pb[2][0].decode("utf-8") == "g"      # unit: the remainder
    # and _item_from_wire reads it back correctly, preferring rawQuantity
    assert _item_from_wire(raw).quantity == "500 g"


def test_item_to_wire_bare_number_has_no_unit_subfield():
    raw = _item_to_wire(identifier="i1", list_id="L1", name="Eggs", quantity="12")
    qty_pb = _decode_message(_decode_message(raw)[21][0])
    assert qty_pb[3][0].decode("utf-8") == "12"
    assert qty_pb[1][0].decode("utf-8") == "12"
    assert 2 not in qty_pb  # no unit field at all when there's nothing after the number


def test_item_to_wire_non_numeric_quantity_still_sets_rawquantity_only():
    """A coarse-ingredient-style string with no leading number ("2 x bunch") can't be split
    into amount/unit by PR #62's regex -- rawQuantity alone still carries it, which is enough
    for AnyList's app to render (per the same live-confirmed rule) and enough for our own reads
    to round-trip correctly."""
    raw = _item_to_wire(identifier="i1", list_id="L1", name="Basil", quantity="bunch")
    qty_pb = _decode_message(_decode_message(raw)[21][0])
    assert qty_pb[3][0].decode("utf-8") == "bunch"
    assert 1 not in qty_pb and 2 not in qty_pb
    assert _item_from_wire(raw).quantity == "bunch"


def test_item_to_wire_empty_quantity_writes_no_quantitypb_at_all():
    raw = _item_to_wire(identifier="i1", list_id="L1", name="Eggs", quantity="")
    assert 21 not in _decode_message(raw)
    raw_none = _item_to_wire(identifier="i1", list_id="L1", name="Eggs", quantity=None)
    assert 21 not in _decode_message(raw_none)


def test_item_from_wire_combines_amount_and_unit_when_no_rawquantity():
    """An item that only ever has amount+unit set (no rawQuantity sub-field at all -- e.g. one
    written by some other client, or an older row) should still read back as a sensible combined
    string rather than just the bare number."""
    qty_pb = _field_string(1, "500") + _field_string(2, "g")
    raw = _field_string(1, "i1") + _field_string(4, "Beef Mince") + _field_message(21, qty_pb)
    assert _item_from_wire(raw).quantity == "500 g"


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


def test_fake_mode_add_populates_added_ids(monkeypatch):
    """2026-09-19 fix (Phase B3): `added_ids` must be populated in fake mode too, since
    checklist.py reads it regardless of real/fake -- and most of the test suite runs fake."""
    _fake_mode(monkeypatch)
    monkeypatch.setattr(ac.settings, "anylist_target_list_name", "TestList", raising=False)

    res = ac.add_or_increment_items([PushItem(name="passata", quantity="400g")])
    assert res.added_ids.keys() == {"passata"}
    new_id = res.added_ids["passata"]
    assert next(i for i in ac.get_items() if i.name == "passata").identifier == new_id



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
            # 2026-09-20: quantityPb now carries rawQuantity (field 3, the full text) ahead of
            # amount (field 1, just the parsed leading number) -- mirror anylist_wire's own
            # read-priority so this helper reflects what the client actually meant to send.
            qty_pb = _decode_message(bytes(item[21][0]))
            raw = qty_pb.get(3, [b""])[0].decode() or None
            qty = raw if raw is not None else (qty_pb.get(1, [b""])[0].decode() or None)
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


def test_real_update_clears_field_21_and_our_confirm_still_passes(monkeypatch):
    """Fault-finding spike (2026-09-18): pins down, as a named test rather than only a code
    comment, the exact gap between "our app thinks this succeeded" and "the field AnyList's own
    UI needs is gone". An item that starts with BOTH field 21 (quantityPb, what a fresh add
    writes) and field 18 (deprecatedQuantity) gets updated via set-list-item-quantity; the
    server's post-update state (as this connector has always found it — spike/FINDINGS.md,
    Chunk 5.7) carries field 18 only. Our own merge-on-read (field 21 preferred, 18 fallback)
    means `confirmed` still comes back True — that's not a bug in the confirm logic, it's the
    reason nothing caught this sooner. See docs/build-status/anylist-fault-finding-spike.md for
    whether AnyList's own app also needs field 21 to render its list-view quantity chip (that
    part can only be settled live, against TestList)."""
    item_before = (
        _field_string(1, "existing1") + _field_string(4, "Milk")
        + _field_string(18, "2L") + _field_message(21, _field_string(1, "2L"))
    )
    item_after = _field_string(1, "existing1") + _field_string(4, "Milk") + _field_string(18, "3L")
    # sanity on the fixtures themselves: "after" really has lost field 21, "before" has both
    assert 21 not in _decode_message(item_after)
    assert 21 in _decode_message(item_before) and 18 in _decode_message(item_before)

    def _wrap(item_bytes: bytes) -> bytes:
        wire_list = _field_string(1, "L1") + _field_string(3, "TestList") + _field_message(4, item_bytes)
        return _field_message(1, _field_message(1, wire_list))

    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            state["gets"] += 1
            return httpx.Response(200, content=_wrap(item_before if state["gets"] == 1 else item_after))
        if request.url.path == "/data/shopping-lists/update":
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    res = ac.add_or_increment_items(
        [PushItem(name="Milk", quantity="3L", existing_id="existing1")], list_name="TestList"
    )
    assert res.confirmed is True and not res.discrepancies  # our merge-on-read masks the loss

    again = ac.get_items("TestList")
    assert again[0].quantity == "3L"  # still correct via the field-18 fallback...
    assert 21 not in _decode_message(item_after)  # ...but the field AnyList's UI may need is gone


def test_update_with_no_quantity_sends_empty_string_value(monkeypatch):
    """checklist.py:292 sends `it.quantity or ""` — an already-on-the-list item that resolves to
    no quantity string (e.g. a coarse ingredient with neither a numeric total nor a pack string)
    pushes an explicit empty-string update rather than leaving the item's quantity untouched.
    Pinning down today's actual wire behaviour rather than assuming it (see fault-finding spike
    Part B, probe 6, for what AnyList's server actually does with an empty update)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes([("existing1", "Milk", "2L")]))
        if request.url.path == "/data/shopping-lists/update":
            assert _updated_value_from_multipart(request.content) == ""
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    ac.add_or_increment_items(
        [PushItem(name="Milk", quantity=None, existing_id="existing1")], list_name="TestList"
    )


def test_update_op_never_carries_a_checked_field():
    """The connector's update path only ever calls `_build_operation` with `updated_value`, never
    `item_wire` — so a quantity-update op has no way to touch the item's checked state at all.
    Made explicit as a test (rather than left implicit in the code) because it's the fact that
    rules out one plausible explanation for "did pushing a quantity update un-tick something a
    household member already checked off on their phone" (fault-finding spike Part B, probe 4)."""
    from app.services.anylist_wire import _build_operation

    op = _build_operation(
        handler_id="set-list-item-quantity", list_id="L1", list_item_id="i1", updated_value="3",
    )
    fields = _decode_message(op)
    assert 4 in fields  # the quantity value itself
    assert 6 not in fields  # no embedded item message -> no checked bit, no name, nothing else


def test_real_update_retries_once_and_recovers(monkeypatch):
    """2026-09-19 fix (Phase B1, docs/build-status/anylist-fault-finding-spike.md): a fraction
    of set-list-item-quantity calls silently persist nothing at all (confirmed live, real
    AnyList-side flakiness). The connector now retries a still-wrong item instead of surfacing
    a discrepancy on the first confirm-refetch. This mock server rejects the first attempt
    (state doesn't change) and accepts the retry -- proves the retry both fires and stops once
    the item is actually correct."""
    calls = {"gets": 0, "posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            calls["gets"] += 1
            # call 1: pre-push state. call 2: after the FIRST post -- simulate the silent
            # failure (quantity unchanged). call 3+: after the retry -- now correct.
            qty = "5L" if calls["gets"] >= 3 else "2L"
            return httpx.Response(200, content=_user_data_bytes([("existing1", "Milk", qty)]))
        if request.url.path == "/data/shopping-lists/update":
            calls["posts"] += 1
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    monkeypatch.setattr(ac, "_RETRY_BACKOFF_S", 0.0, raising=False)  # don't slow the test down
    res = ac.add_or_increment_items(
        [PushItem(name="Milk", quantity="5L", existing_id="existing1")], list_name="TestList"
    )

    assert res.confirmed is True and not res.discrepancies
    assert res.retried == ["Milk"]
    assert res.updated == ["Milk"]
    assert calls["posts"] == 2  # initial attempt + exactly one retry, no more
    assert calls["gets"] == 3  # pre-push + post-initial-check + post-retry-check


def test_real_update_gives_up_after_exhausting_retries(monkeypatch):
    """The mirror case: the mock server never accepts the update at all. Confirms the retry
    loop is bounded (_MAX_RETRIES) and still ends with a real, surfaced discrepancy -- never
    silently drops it just because a retry was attempted."""
    calls = {"posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/data/user-data/get":
            return httpx.Response(200, content=_user_data_bytes([("existing1", "Milk", "2L")]))
        if request.url.path == "/data/shopping-lists/update":
            calls["posts"] += 1
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    _real_client(monkeypatch, handler)
    monkeypatch.setattr(ac, "_RETRY_BACKOFF_S", 0.0, raising=False)
    res = ac.add_or_increment_items(
        [PushItem(name="Milk", quantity="5L", existing_id="existing1")], list_name="TestList"
    )

    assert res.confirmed is False
    assert res.retried == ["Milk"] * ac._MAX_RETRIES
    assert res.discrepancies and "quantity is" in res.discrepancies[0]
    assert calls["posts"] == 1 + ac._MAX_RETRIES  # initial + every retry attempted


def test_real_get_items_unknown_list_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, content=_user_data_bytes([("i1", "Milk", "2L")]))

    _real_client(monkeypatch, handler)
    with pytest.raises(AnyListError):
        ac.get_items("NoSuchList")

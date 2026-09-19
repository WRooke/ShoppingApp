"""AnyList's protobuf wire format — split out of ``services/anylist_client.py`` (2026-09-13
code review) per CLAUDE.md > Code Architecture > File size and scope discipline. Pure
encode/decode: no network, no ``settings``, no ``httpx``. ``anylist_client.py`` re-exports
everything here (same precedent as ``ai_extraction.py`` -> the ``ai_extraction/`` package) so
no call site — including the existing test suite, which imports several of these by name —
needed to change.

Lifted from ``spike/anylist_spike.py`` (Phase 1.5 derisking spike); see
``anylist_client.py``'s own module docstring for the load-bearing live-verification findings
about what the decoded fields actually mean (which fields carry quantity, etc.) — those are
connector-behaviour concerns, not wire-format ones, so they stay there.
"""

from __future__ import annotations

import re
import struct
import uuid
from dataclasses import dataclass

_WIRE_VARINT, _WIRE_FIXED64, _WIRE_LEN, _WIRE_FIXED32 = 0, 1, 2, 5


# --- public type ------------------------------------------------------------------------
#
# Lives here (not anylist_client.py) because _item_from_wire/_item_to_wire/_WireList below
# all construct or consume it directly — re-exported from anylist_client for every other
# caller, which only ever needs the public shape, never the wire functions.


@dataclass(frozen=True)
class AnyListItem:
    """One item on an AnyList shopping list, as the app cares about it.

    ``note`` (protobuf field 5, AnyList's "details") added at the Chunk 5.7 live-verification
    fix — previously this type had no way to represent it at all, which is part of why the
    update-path note bug (see ``anylist_client._RealAnyList.add_or_increment_items``) went
    undetected."""

    identifier: str
    name: str | None
    quantity: str | None
    checked: bool | None
    note: str | None = None


# --- encode ------------------------------------------------------------------------------


def _encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field_num: int, wire_type: int) -> bytes:
    return _encode_varint((field_num << 3) | wire_type)


def _field_string(field_num: int, value: str | None) -> bytes:
    if value is None:
        return b""
    data = value.encode("utf-8")
    return _tag(field_num, _WIRE_LEN) + _encode_varint(len(data)) + data


def _field_bool(field_num: int, value: bool | None) -> bytes:
    if value is None:
        return b""
    return _tag(field_num, _WIRE_VARINT) + _encode_varint(1 if value else 0)


def _field_message(field_num: int, payload: bytes | None) -> bytes:
    if not payload:
        return b""
    return _tag(field_num, _WIRE_LEN) + _encode_varint(len(payload)) + payload


# --- decode ------------------------------------------------------------------------------


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _decode_message(data: bytes) -> dict[int, list]:
    """Generic protobuf decode: field number -> list of raw values. Length-delimited values
    stay as raw bytes (caller decides string vs nested message).

    Raises a plain ``ValueError`` on an unrecognised wire type — this module has no
    AnyList-specific exception of its own (no network/settings dependency to hang one off);
    every caller in ``anylist_client.py`` already wraps any decode failure into
    ``AnyListError`` via a generic ``except Exception``, so there's nothing for a bespoke
    exception type here to add."""
    fields: dict[int, list] = {}
    pos, length = 0, len(data)
    while pos < length:
        tag, pos = _decode_varint(data, pos)
        field_num, wire_type = tag >> 3, tag & 0x7
        if wire_type == _WIRE_VARINT:
            value, pos = _decode_varint(data, pos)
        elif wire_type == _WIRE_FIXED64:
            value = struct.unpack_from("<d", data, pos)[0]
            pos += 8
        elif wire_type == _WIRE_LEN:
            n, pos = _decode_varint(data, pos)
            value = data[pos : pos + n]
            pos += n
        elif wire_type == _WIRE_FIXED32:
            value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type} at byte {pos}")
        fields.setdefault(field_num, []).append(value)
    return fields


def _s(fields: dict[int, list], num: int) -> str | None:
    values = fields.get(num)
    return values[0].decode("utf-8") if values else None


def _b(fields: dict[int, list], num: int) -> bool | None:
    values = fields.get(num)
    return bool(values[0]) if values else None


def _item_from_wire(raw: bytes) -> AnyListItem:
    f = _decode_message(raw)
    quantity = None
    if 21 in f:
        qty_pb = _decode_message(f[21][0])
        # rawQuantity (3, the full text a user typed) first, then amount(1)+unit(2) combined,
        # both ahead of amount alone -- matches AnyList's own apparent read priority (2026-09-19
        # fault-finding spike / PR #62 on the reference library: the apps render rawQuantity for
        # display, not amount alone -- see anylist_client.py's module docstring).
        quantity = _s(qty_pb, 3)
        if quantity is None:
            amount, unit = _s(qty_pb, 1), _s(qty_pb, 2)
            quantity = f"{amount} {unit}" if amount and unit else amount
    if quantity is None and 18 in f:  # deprecatedQuantity — legacy, set by set-list-item-quantity
        quantity = _s(f, 18)
    return AnyListItem(
        identifier=_s(f, 1) or "", name=_s(f, 4), quantity=quantity, checked=_b(f, 6),
        note=_s(f, 5),
    )


# PR #62's own parsing rule (unmerged upstream, github.com/kevdliu/anylist) — a leading
# int-or-decimal number, then whatever's left over as the unit.
_LEADING_NUMBER = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.*)$")


def _split_quantity(raw: str) -> tuple[str | None, str | None, str | None]:
    """(rawQuantity, amount, unit) the PR #62 way. Empty/blank input -> all None (no quantityPb
    written at all, matching the pre-fix `if quantity:` guard)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None, None
    m = _LEADING_NUMBER.match(raw)
    if not m:
        return raw, None, None
    amount, unit = m.group(1), m.group(2)
    return raw, amount, (unit or None)


def _item_to_wire(
    *,
    identifier: str,
    list_id: str,
    name: str | None,
    quantity: str | None,
    details: str | None = None,
    checked: bool = False,
) -> bytes:
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_string(5, details)  # AnyList's free-text "details"/notes field on an item
    # `checked` defaults to False (a genuinely new item lands unchecked) but is overridable —
    # 2026-09-20 fix (fault-finding spike, Phase B): the lossless delete+re-add path for
    # unit-bearing quantity updates needs to preserve a checked item's checked state across the
    # cycle, not silently un-tick it. Live-confirmed reliable (6/6): checked=True on add lands
    # as checked on re-fetch.
    out += _field_bool(6, checked)
    # 2026-09-20 fix (fault-finding spike, "Stage 1" addendum): writing quantityPb.amount alone
    # (the whole "500 g" string, non-numeric) left AnyList's own app showing "Not set" for any
    # freshly-added item with a unit — live phone-confirmed against both shapes. AnyList's apps
    # render quantityPb.rawQuantity for display; a non-numeric amount with no rawQuantity shows
    # nothing. rawQuantity now always carries the exact text; amount/unit are the PR #62 parse
    # of it when it has a recognisable leading number, best-effort (some coarse-ingredient
    # strings like "2 x bunch" won't split cleanly — rawQuantity alone still covers them).
    raw_q, amount, unit = _split_quantity(quantity or "")
    if raw_q is not None:
        qty_pb = _field_string(3, raw_q)
        if amount is not None:
            qty_pb += _field_string(1, amount)
        if unit is not None:
            qty_pb += _field_string(2, unit)
        out += _field_message(21, qty_pb)
    return out


@dataclass
class _WireList:
    identifier: str
    name: str | None
    items: list[AnyListItem]

    @classmethod
    def from_wire(cls, raw: bytes) -> "_WireList":
        f = _decode_message(raw)
        return cls(
            identifier=_s(f, 1) or "",
            name=_s(f, 3),
            items=[_item_from_wire(r) for r in f.get(4, [])],
        )


def _parse_user_data(raw: bytes) -> list[_WireList]:
    top = _decode_message(raw)
    outer = top.get(1)
    if not outer:
        return []
    inner = _decode_message(outer[0])
    return [_WireList.from_wire(r) for r in inner.get(1, [])]


def _build_operation(
    *, handler_id: str, list_id: str, list_item_id: str,
    item_wire: bytes | None = None, updated_value: str | None = None,
) -> bytes:
    metadata = _field_string(1, uuid.uuid4().hex) + _field_string(2, handler_id)
    op = _field_message(1, metadata) + _field_string(2, list_id) + _field_string(3, list_item_id)
    if updated_value is not None:
        op += _field_string(4, updated_value)
    if item_wire is not None:
        op += _field_message(6, item_wire)
    return op


def _build_operation_list(operations: list[bytes]) -> bytes:
    return b"".join(_field_message(1, op) for op in operations)

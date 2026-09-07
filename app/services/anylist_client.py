"""AnyList connector — Python-native, Phase 5 (see CLAUDE.md > Build Phases > Phase 5 and
> Tech Stack > AnyList integration).

One external integration behind one small, stable interface (CLAUDE.md > Code Architecture >
"External integrations sit behind a small, stable interface"): the rest of the app calls
``get_items()`` / ``add_or_increment_items()`` / ``check_auth()`` and never touches
``httpx`` or the protobuf wire format directly. No ``fastapi`` import.

The wire codec and message shapes are lifted from ``spike/anylist_spike.py`` (Phase 1.5
derisking spike) — AnyList's API is unofficial, reverse-engineered from the Node package
``codetheweb/anylist``, and speaks raw protobuf with no public ``.proto``. Three spike
findings are load-bearing here:

  * **Quantity lives in two fields.** A freshly *added* item carries ``quantityPb.amount``
    (field 21); an item whose quantity was later *updated* via ``set-list-item-quantity``
    carries the legacy flat ``deprecatedQuantity`` (field 18) instead. Read field 21 first,
    fall back to field 18.
  * **The ``operations`` multipart part must have no filename.** With one, the server returns
    HTTP 200 and silently does nothing.
  * **A batch POST returns 200 even if some ops were no-ops.** Push success can't be trusted
    from the status — always re-fetch and diff against intent.

Safety (CLAUDE.md > Security §2, mirrors §0c for the AI): every real call is gated on
``settings.anylist_enabled`` (default off — no agent flips it). ``settings.anylist_fake_mode``
swaps in an in-memory fake list so the whole checklist + push flow runs offline. Manual
verification runs only against ``settings.anylist_target_list_name`` (dev default
``TestList``); the real household list is never touched without a fresh per-occasion
go-ahead.
"""

from __future__ import annotations

import logging
import struct
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.config import settings
from app.database import utcnow

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anylist.com"
_TIMEOUT = 15.0


# --- public types ---------------------------------------------------------------------


@dataclass(frozen=True)
class AnyListItem:
    """One item on an AnyList shopping list, as the app cares about it."""

    identifier: str
    name: str | None
    quantity: str | None
    checked: bool | None


@dataclass(frozen=True)
class PushItem:
    """One line the app wants on the list. ``existing_id`` set => update that item's quantity
    in place (don't add a duplicate); ``None`` => add a new item."""

    name: str
    quantity: str | None
    existing_id: str | None = None


@dataclass
class PushResult:
    added: list[str] = field(default_factory=list)     # names added
    updated: list[str] = field(default_factory=list)   # names whose quantity was set
    confirmed: bool = False                            # re-fetch + diff matched intent
    discrepancies: list[str] = field(default_factory=list)
    raw_response: str | None = None                    # for shopping_history / diagnostics


@dataclass(frozen=True)
class AuthStatus:
    ok: bool
    detail: str
    checked_at: datetime


# --- exceptions ---------------------------------------------------------------------


class AnyListError(Exception):
    """Any AnyList failure the app should surface (network, protocol, unexpected shape).
    Translated to a 502 envelope in app/main.py."""


class AnyListAuthError(AnyListError):
    """Authentication with AnyList failed (bad credentials, or a 401 that a re-login didn't
    fix). 502 with its own code."""


class AnyListDisabledError(Exception):
    """A real AnyList call was attempted with settings.anylist_enabled False. 503 in
    app/main.py — same shape as AiExtractionDisabledError."""


# --- protobuf wire codec (from spike/anylist_spike.py) -------------------------------

_WIRE_VARINT, _WIRE_FIXED64, _WIRE_LEN, _WIRE_FIXED32 = 0, 1, 2, 5


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
    stay as raw bytes (caller decides string vs nested message)."""
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
            raise AnyListError(f"unsupported protobuf wire type {wire_type} at byte {pos}")
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
    if 21 in f:  # quantityPb.amount — current, set on add
        quantity = _s(_decode_message(f[21][0]), 1)
    if quantity is None and 18 in f:  # deprecatedQuantity — legacy, set by set-list-item-quantity
        quantity = _s(f, 18)
    return AnyListItem(
        identifier=_s(f, 1) or "", name=_s(f, 4), quantity=quantity, checked=_b(f, 6)
    )


def _item_to_wire(*, identifier: str, list_id: str, name: str | None, quantity: str | None) -> bytes:
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_bool(6, False)  # new items land unchecked
    if quantity:
        out += _field_message(21, _field_string(1, quantity))
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


# --- real connector ---------------------------------------------------------------------


class _RealAnyList:
    """Talks to www.anylist.com. Instantiated once per process and cached; a 401 on a data
    call triggers one fresh full re-login + retry (the spike didn't exercise token refresh,
    so we just re-auth with the credentials we already hold)."""

    def __init__(self, email: str, password: str) -> None:
        if not email or not password or "REPLACE_ME" in email or "REPLACE_ME" in password:
            raise AnyListAuthError("AnyList credentials are not configured (see Security §2)")
        self._email = email
        self._password = password
        self._client_id = uuid.uuid4().hex
        self._token: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT)

    # -- auth --
    def login(self) -> None:
        logger.info("AnyList: authenticating as %s", self._email)
        try:
            resp = self._http.post(
                "/auth/token",
                headers={"X-AnyLeaf-API-Version": "3"},
                files={"email": (None, self._email), "password": (None, self._password)},
            )
        except httpx.HTTPError as exc:
            raise AnyListAuthError(f"could not reach AnyList to authenticate: {exc}") from exc
        if resp.status_code != 200:
            logger.error("AnyList auth failed: status=%s body=%s", resp.status_code, resp.text[:300])
            raise AnyListAuthError(f"AnyList rejected the credentials (HTTP {resp.status_code})")
        try:
            self._token = resp.json()["access_token"]
        except (ValueError, KeyError) as exc:
            raise AnyListAuthError("AnyList auth response had no access_token") from exc
        logger.info("AnyList: authenticated")

    def _headers(self) -> dict[str, str]:
        return {
            "X-AnyLeaf-API-Version": "3",
            "X-AnyLeaf-Client-Identifier": self._client_id,
            "authorization": f"Bearer {self._token}",
        }

    def _data_post(self, path: str, *, files=None) -> httpx.Response:
        """POST to a /data/ endpoint, logging in first if needed and re-logging once on a 401."""
        if self._token is None:
            self.login()
        for attempt in (1, 2):
            try:
                resp = self._http.post(path, headers=self._headers(), files=files)
            except httpx.HTTPError as exc:
                raise AnyListError(f"AnyList request to {path} failed: {exc}") from exc
            if resp.status_code == 401 and attempt == 1:
                logger.warning("AnyList: 401 on %s — re-authenticating and retrying once", path)
                self.login()
                continue
            if resp.status_code != 200:
                logger.error("AnyList %s failed: status=%s body=%r", path, resp.status_code, resp.content[:300])
                raise AnyListError(f"AnyList {path} returned HTTP {resp.status_code}")
            return resp
        raise AnyListError(f"AnyList {path} still 401 after re-authenticating")

    # -- reads --
    def _get_lists(self) -> list[_WireList]:
        resp = self._data_post("/data/user-data/get")
        try:
            return _parse_user_data(resp.content)
        except AnyListError:
            raise
        except Exception as exc:  # noqa: BLE001 — a decode failure is still an AnyListError
            raise AnyListError(f"could not parse AnyList user-data response: {exc}") from exc

    def _resolve_list(self, list_name: str) -> _WireList:
        lists = self._get_lists()
        match = next((l for l in lists if (l.name or "").strip() == list_name.strip()), None)
        if match is None:
            raise AnyListError(
                f"AnyList list {list_name!r} not found on this account "
                f"(available: {[l.name for l in lists]})"
            )
        return match

    def get_items(self, list_name: str) -> list[AnyListItem]:
        return list(self._resolve_list(list_name).items)

    def check_auth(self) -> AuthStatus:
        try:
            self.login()
            return AuthStatus(True, "Authenticated", utcnow())
        except AnyListError as exc:
            return AuthStatus(False, str(exc), utcnow())

    # -- writes --
    def add_or_increment_items(self, list_name: str, items: list[PushItem]) -> PushResult:
        target = self._resolve_list(list_name)
        before = {i.identifier: i for i in target.items}
        result = PushResult()
        ops: list[bytes] = []
        planned: list[tuple[str, str, str | None]] = []  # (op_kind, identifier, expected_qty)

        for it in items:
            if it.existing_id and it.existing_id in before:
                ops.append(
                    _build_operation(
                        handler_id="set-list-item-quantity",
                        list_id=target.identifier,
                        list_item_id=it.existing_id,
                        updated_value=it.quantity or "",
                    )
                )
                planned.append(("update", it.existing_id, it.quantity or ""))
                result.updated.append(it.name)
            else:
                new_id = uuid.uuid4().hex
                ops.append(
                    _build_operation(
                        handler_id="add-shopping-list-item",
                        list_id=target.identifier,
                        list_item_id=new_id,
                        item_wire=_item_to_wire(
                            identifier=new_id, list_id=target.identifier,
                            name=it.name, quantity=it.quantity,
                        ),
                    )
                )
                planned.append(("add", new_id, it.quantity))
                result.added.append(it.name)

        if not ops:
            result.confirmed = True
            return result

        resp = self._data_post(
            "/data/shopping-lists/update",
            files={"operations": (None, _build_operation_list(ops), "application/octet-stream")},
        )
        result.raw_response = f"HTTP {resp.status_code}; {len(resp.content)} bytes"

        # Spike finding: a 200 doesn't mean every op landed. Re-fetch and diff against intent.
        after = {i.identifier: i for i in self._resolve_list(list_name).items}
        for kind, ident, expected_qty in planned:
            got = after.get(ident)
            if kind == "add" and got is None:
                result.discrepancies.append(f"add {ident} did not land")
            elif kind == "update" and got is not None and expected_qty and got.quantity != expected_qty:
                result.discrepancies.append(
                    f"update {ident}: quantity is {got.quantity!r}, expected {expected_qty!r}"
                )
        result.confirmed = not result.discrepancies
        if not result.confirmed:
            logger.error("AnyList push not fully confirmed: %s", result.discrepancies)
        return result


# --- in-memory fake ---------------------------------------------------------------------

# Deterministic seed so the checklist pre-tick path always has something to match against in
# fake mode. Keyed by list name -> {item_id: AnyListItem}.
_FAKE_SEED = {
    "milk": ("2L bottle", False),
    "eggs": ("1 dozen", False),
    "butter": (None, True),
}


class _FakeAnyList:
    def __init__(self) -> None:
        self._lists: dict[str, dict[str, AnyListItem]] = {}
        target = settings.anylist_target_list_name
        self._lists[target] = {
            f"seed-{name}": AnyListItem(f"seed-{name}", name, qty, checked)
            for name, (qty, checked) in _FAKE_SEED.items()
        }

    def _list(self, list_name: str) -> dict[str, AnyListItem]:
        return self._lists.setdefault(list_name, {})

    def get_items(self, list_name: str) -> list[AnyListItem]:
        return list(self._list(list_name).values())

    def check_auth(self) -> AuthStatus:
        return AuthStatus(True, "FAKE MODE — no real AnyList call", utcnow())

    def add_or_increment_items(self, list_name: str, items: list[PushItem]) -> PushResult:
        lst = self._list(list_name)
        result = PushResult()
        for it in items:
            if it.existing_id and it.existing_id in lst:
                old = lst[it.existing_id]
                lst[it.existing_id] = AnyListItem(old.identifier, old.name, it.quantity, old.checked)
                result.updated.append(it.name)
            else:
                new_id = f"fake-{uuid.uuid4().hex[:8]}"
                lst[new_id] = AnyListItem(new_id, it.name, it.quantity, False)
                result.added.append(it.name)
        result.confirmed = True
        result.raw_response = "FAKE MODE"
        return result


# --- module surface -------------------------------------------------------------------

_lock = threading.Lock()
_instance: _RealAnyList | _FakeAnyList | None = None
_last_ok_at: datetime | None = None


def _mark_ok() -> None:
    global _last_ok_at
    _last_ok_at = utcnow()


def last_success_at() -> datetime | None:
    """When a real (or fake) AnyList call last succeeded this process. Diagnostics reads this
    rather than doing a live round-trip on every auto-poll."""
    return _last_ok_at


def _get_client() -> _RealAnyList | _FakeAnyList:
    """The process-wide connector. Fake when settings.anylist_fake_mode; otherwise a real
    client gated on settings.anylist_enabled. Cached — a real client keeps its token across
    calls (and re-logs in on a 401 itself)."""
    global _instance
    with _lock:
        if settings.anylist_fake_mode:
            if not isinstance(_instance, _FakeAnyList):
                _instance = _FakeAnyList()
            return _instance
        if not settings.anylist_enabled:
            raise AnyListDisabledError(
                "AnyList is disabled — set ANYLIST_ENABLED=true (and see Security §2) to make "
                "real calls, or ANYLIST_FAKE_MODE=true for offline development."
            )
        if not isinstance(_instance, _RealAnyList):
            _instance = _RealAnyList(settings.anylist_email, settings.anylist_password)
        return _instance


def reset_client() -> None:
    """Drop the cached connector (used by tests, and after a config change)."""
    global _instance
    with _lock:
        _instance = None


def get_items(list_name: str | None = None) -> list[AnyListItem]:
    """Current items on the target list (defaults to settings.anylist_target_list_name)."""
    name = list_name or settings.anylist_target_list_name
    result = _get_client().get_items(name)
    _mark_ok()
    return result


def add_or_increment_items(
    items: list[PushItem], *, list_name: str | None = None
) -> PushResult:
    """Push a batch: add new items, set the quantity on ones already present (no duplicates),
    then re-fetch + diff to confirm. See CLAUDE.md > AnyList Push Logic."""
    name = list_name or settings.anylist_target_list_name
    result = _get_client().add_or_increment_items(name, items)
    _mark_ok()
    return result


def check_auth() -> AuthStatus:
    """For the diagnostics panel — does a real (or fake) auth round-trip and returns a
    timestamped status. Never raises."""
    try:
        status = _get_client().check_auth()
        if status.ok:
            _mark_ok()
        return status
    except AnyListDisabledError as exc:
        return AuthStatus(False, str(exc), utcnow())
    except AnyListError as exc:
        return AuthStatus(False, str(exc), utcnow())

"""AnyList derisking spike (Phase 1.5 — CLAUDE.md > AnyList derisking spike).

Throwaway script. NOT wired into the app — do not import this from app/.

Goal: prove the Python-native approach (httpx + a hand-rolled protobuf
codec) can authenticate against AnyList, fetch a list, add an item, and
remove it again — using the real .env credentials.

Reference implementation: the Node.js package `codetheweb/anylist`
(https://github.com/codetheweb/anylist), read directly from its `lib/`
source (index.js, list.js, item.js, definitions.json) to determine the
HTTP endpoints, headers, and protobuf message shapes below. AnyList's API
is unofficial and reverse-engineered — none of this is documented by
AnyList itself.

Usage:
    .venv\\Scripts\\python.exe -m spike.anylist_spike

Reads ANYLIST_EMAIL / ANYLIST_PASSWORD / ANYLIST_TARGET_LIST_NAME from the
project's .env (same file the app uses). The target list must already
exist in the AnyList account — this spike does not create lists.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("anylist_spike")

BASE_URL = "https://www.anylist.com"

# Easy to change later: set ANYLIST_TARGET_LIST_NAME in .env. Defaults to
# the dev list so nobody accidentally points this at the real household
# list by forgetting a flag.
TARGET_LIST_NAME = os.getenv("ANYLIST_TARGET_LIST_NAME", "TestList")


# --------------------------------------------------------------------------
# Minimal protobuf wire-format codec.
#
# AnyList's API is unofficial and speaks raw protobuf, but there is no
# public .proto file — only a protobufjs-style JSON descriptor
# (definitions.json) in the reference Node package. Rather than pull in
# protoc/grpc tooling for a throwaway spike, this hand-rolls the handful
# of messages actually needed, straight off that descriptor:
#
#   PBOperationMetadata { 1:string operationId, 2:string handlerId, 3:string userId }
#   ListItem            { 1:string identifier, 3:string listId, 4:string name,
#                          5:string details, 6:bool checked, 21:PBItemQuantity quantityPb }
#   PBItemQuantity      { 1:string amount }
#   PBListOperation     { 1:PBOperationMetadata metadata, 2:string listId,
#                          3:string listItemId, 6:ListItem listItem }
#   PBListOperationList { 1:repeated PBListOperation operations }
#
#   PBUserDataResponse    { 1:ShoppingListsResponse shoppingListsResponse }
#   ShoppingListsResponse { 1:repeated ShoppingList newLists }
#   ShoppingList          { 1:string identifier, 3:string name, 4:repeated ListItem items }
# --------------------------------------------------------------------------

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5


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


def field_string(field_num: int, value: str | None) -> bytes:
    if value is None:
        return b""
    data = value.encode("utf-8")
    return _tag(field_num, WIRE_LEN) + _encode_varint(len(data)) + data


def field_bool(field_num: int, value: bool | None) -> bytes:
    if value is None:
        return b""
    return _tag(field_num, WIRE_VARINT) + _encode_varint(1 if value else 0)


def field_message(field_num: int, payload: bytes | None) -> bytes:
    if not payload:
        return b""
    return _tag(field_num, WIRE_LEN) + _encode_varint(len(payload)) + payload


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def decode_message(data: bytes) -> dict[int, list]:
    """Generic protobuf decode: field number -> list of raw values.

    Length-delimited fields are returned as raw bytes (caller decides
    whether that's a nested message or a UTF-8 string). Sufficient for
    reading AnyList responses without a schema compiler.
    """
    fields: dict[int, list] = {}
    pos = 0
    length = len(data)
    while pos < length:
        tag, pos = _decode_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type == WIRE_VARINT:
            value, pos = _decode_varint(data, pos)
        elif wire_type == WIRE_FIXED64:
            value = struct.unpack_from("<d", data, pos)[0]
            pos += 8
        elif wire_type == WIRE_LEN:
            n, pos = _decode_varint(data, pos)
            value = data[pos : pos + n]
            pos += n
        elif wire_type == WIRE_FIXED32:
            value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire_type} at byte {pos}")
        fields.setdefault(field_num, []).append(value)
    return fields


def _s(fields: dict[int, list], num: int) -> str | None:
    """First length-delimited field value, decoded as UTF-8."""
    values = fields.get(num)
    return values[0].decode("utf-8") if values else None


def _b(fields: dict[int, list], num: int) -> bool | None:
    values = fields.get(num)
    return bool(values[0]) if values else None


@dataclass
class ListItem:
    identifier: str
    name: str | None = None
    checked: bool | None = None
    quantity: str | None = None

    @classmethod
    def from_wire(cls, raw: bytes) -> "ListItem":
        f = decode_message(raw)
        # Same precedence as the reference client's Item constructor:
        # quantityPb.amount (field 21, current) falls back to
        # deprecatedQuantity (field 18, legacy flat string) — the
        # `set-list-item-quantity` operation handler writes the legacy
        # field, not quantityPb, so both must be checked.
        quantity = None
        if 21 in f:
            quantity = _s(decode_message(f[21][0]), 1)
        if quantity is None and 18 in f:
            quantity = _s(f, 18)
        return cls(
            identifier=_s(f, 1) or "",
            name=_s(f, 4),
            checked=_b(f, 6),
            quantity=quantity,
        )

    def to_wire(self, list_id: str) -> bytes:
        out = b""
        out += field_string(1, self.identifier)
        out += field_string(3, list_id)
        out += field_string(4, self.name)
        if self.checked is not None:
            out += field_bool(6, self.checked)
        if self.quantity:
            out += field_message(21, field_string(1, self.quantity))
        return out


@dataclass
class ShoppingList:
    identifier: str
    name: str | None = None
    items: list[ListItem] = field(default_factory=list)

    @classmethod
    def from_wire(cls, raw: bytes) -> "ShoppingList":
        f = decode_message(raw)
        items = [ListItem.from_wire(raw_item) for raw_item in f.get(4, [])]
        return cls(identifier=_s(f, 1) or "", name=_s(f, 3), items=items)


def parse_user_data_response(raw: bytes) -> list[ShoppingList]:
    top = decode_message(raw)
    shopping_lists_response = top.get(1)
    if not shopping_lists_response:
        return []
    inner = decode_message(shopping_lists_response[0])
    return [ShoppingList.from_wire(raw_list) for raw_list in inner.get(1, [])]


def build_operation(
    *,
    handler_id: str,
    list_id: str,
    list_item_id: str,
    list_item: ListItem | None = None,
    updated_value: str | None = None,
) -> bytes:
    """Build one PBListOperation.

    Two distinct shapes exist in the reference client, both handled here:
    - add/remove (list.js): carries a full `listItem` submessage (field 6).
    - single-field updates (item.js `save()`, e.g. `set-list-item-quantity`):
      carries only `updatedValue` (field 4) as a plain string — no listItem.
    """
    metadata = field_string(1, uuid.uuid4().hex) + field_string(2, handler_id)
    # userId (field 3) intentionally omitted: the reference Node client
    # never populates it either (`this.uid` is destructured from the
    # AnyList instance but that instance never sets it) — the server
    # evidently derives ownership from the bearer token instead.
    op = field_message(1, metadata)
    op += field_string(2, list_id)
    op += field_string(3, list_item_id)
    if updated_value is not None:
        op += field_string(4, updated_value)
    if list_item is not None:
        op += field_message(6, list_item.to_wire(list_id))
    return op


def build_operation_list(operations: list[bytes]) -> bytes:
    return b"".join(field_message(1, op) for op in operations)


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------


class AnyListSpikeClient:
    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.client_id = uuid.uuid4().hex
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=15.0)

    def login(self) -> None:
        logger.info("Authenticating with AnyList as %s", self.email)
        # Reference client posts multipart/form-data (Node's `form-data`
        # package), not urlencoded — replicate that with httpx's `files=`
        # so field encoding matches exactly.
        response = self._http.post(
            "/auth/token",
            headers={"X-AnyLeaf-API-Version": "3"},
            files={"email": (None, self.email), "password": (None, self.password)},
        )
        if response.status_code != 200:
            logger.error(
                "AnyList auth failed: status=%s body=%s", response.status_code, response.text
            )
            response.raise_for_status()
        data = response.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        logger.info("Authenticated successfully (access token acquired)")

    def _data_headers(self) -> dict[str, str]:
        return {
            "X-AnyLeaf-API-Version": "3",
            "X-AnyLeaf-Client-Identifier": self.client_id,
            "authorization": f"Bearer {self.access_token}",
        }

    def get_lists(self) -> list[ShoppingList]:
        logger.info("Fetching user data (data/user-data/get)")
        response = self._http.post("/data/user-data/get", headers=self._data_headers())
        if response.status_code != 200:
            logger.error(
                "user-data/get failed: status=%s body=%r", response.status_code, response.content[:500]
            )
            response.raise_for_status()
        lists = parse_user_data_response(response.content)
        logger.info("Fetched %d list(s): %s", len(lists), [l.name for l in lists])
        return lists

    def add_item(self, list_id: str, item: ListItem) -> None:
        logger.info("Adding item %r (%s) to list %s", item.name, item.identifier, list_id)
        op = build_operation(
            handler_id="add-shopping-list-item",
            list_id=list_id,
            list_item_id=item.identifier,
            list_item=item,
        )
        body = build_operation_list([op])
        response = self._http.post(
            "/data/shopping-lists/update",
            headers=self._data_headers(),
            # No filename on this part: the reference client's `form-data`
            # library doesn't set one for a plain Buffer.append(), and the
            # server appears to key off that (a part with a filename lands
            # in a "files" bucket server-side and is silently ignored).
            files={"operations": (None, body, "application/octet-stream")},
        )
        if response.status_code != 200:
            logger.error(
                "add item failed: status=%s body=%r", response.status_code, response.content[:500]
            )
            response.raise_for_status()
        logger.info("Add-item request accepted (HTTP %s)", response.status_code)

    def remove_item(self, list_id: str, item: ListItem) -> None:
        logger.info("Removing item %r (%s) from list %s", item.name, item.identifier, list_id)
        op = build_operation(
            handler_id="remove-shopping-list-item",
            list_id=list_id,
            list_item_id=item.identifier,
            list_item=item,
        )
        body = build_operation_list([op])
        response = self._http.post(
            "/data/shopping-lists/update",
            headers=self._data_headers(),
            files={"operations": (None, body, "application/octet-stream")},
        )
        if response.status_code != 200:
            logger.error(
                "remove item failed: status=%s body=%r", response.status_code, response.content[:500]
            )
            response.raise_for_status()
        logger.info("Remove-item request accepted (HTTP %s)", response.status_code)

    def post_operations(self, operations: list[bytes]) -> httpx.Response:
        """Send one or more PBListOperations in a single HTTP call."""
        body = build_operation_list(operations)
        response = self._http.post(
            "/data/shopping-lists/update",
            headers=self._data_headers(),
            files={"operations": (None, body, "application/octet-stream")},
        )
        logger.info(
            "Posted %d operation(s) in one call -> HTTP %s (body=%r)",
            len(operations),
            response.status_code,
            response.content[:300],
        )
        return response

    def set_item_quantity(self, list_id: str, item_id: str, new_quantity: str) -> httpx.Response:
        logger.info("Setting quantity of item %s on list %s to %r", item_id, list_id, new_quantity)
        op = build_operation(
            handler_id="set-list-item-quantity",
            list_id=list_id,
            list_item_id=item_id,
            updated_value=new_quantity,
        )
        return self.post_operations([op])


def main() -> int:
    email = os.getenv("ANYLIST_EMAIL", "").strip()
    password = os.getenv("ANYLIST_PASSWORD", "").strip()
    if not email or not password or "REPLACE_ME" in email or "REPLACE_ME" in password:
        logger.error("ANYLIST_EMAIL / ANYLIST_PASSWORD not set in .env — cannot run the spike.")
        return 1

    logger.info("=== AnyList derisking spike starting (target list: %r) ===", TARGET_LIST_NAME)

    client = AnyListSpikeClient(email, password)

    try:
        client.login()
    except Exception:
        logger.error("Login step failed", exc_info=True)
        return 1

    try:
        lists = client.get_lists()
    except Exception:
        logger.error("Fetching lists failed", exc_info=True)
        return 1

    target = next((l for l in lists if l.name == TARGET_LIST_NAME), None)
    if target is None:
        logger.error(
            "List %r not found on this account. Available lists: %s. "
            "Create it in the AnyList app first (this spike does not create lists).",
            TARGET_LIST_NAME,
            [l.name for l in lists],
        )
        return 1

    logger.info(
        "Target list %r has %d item(s) before the spike: %s",
        target.name,
        len(target.items),
        [(i.name, i.quantity, i.checked) for i in target.items],
    )

    test_item = ListItem(
        identifier=uuid.uuid4().hex,
        name="ShoppingApp spike test item",
        quantity="1",
        checked=False,
    )

    try:
        client.add_item(target.identifier, test_item)
    except Exception:
        logger.error("Add-item step failed", exc_info=True)
        return 1

    # Re-fetch to prove the add really landed server-side, not just that
    # the POST returned 200.
    try:
        lists_after_add = client.get_lists()
    except Exception:
        logger.error("Re-fetch after add failed", exc_info=True)
        return 1

    target_after_add = next((l for l in lists_after_add if l.identifier == target.identifier), None)
    found_after_add = target_after_add and any(
        i.identifier == test_item.identifier for i in target_after_add.items
    )
    if found_after_add:
        logger.info("CONFIRMED: test item is present on the list after add.")
    else:
        logger.error(
            "Test item NOT found on the list after add — add likely failed silently. Items now: %s",
            [(i.name, i.identifier) for i in (target_after_add.items if target_after_add else [])],
        )
        return 1

    try:
        client.remove_item(target.identifier, test_item)
    except Exception:
        logger.error("Remove-item step failed", exc_info=True)
        return 1

    try:
        lists_after_remove = client.get_lists()
    except Exception:
        logger.error("Re-fetch after remove failed", exc_info=True)
        return 1

    target_after_remove = next(
        (l for l in lists_after_remove if l.identifier == target.identifier), None
    )
    still_present = target_after_remove and any(
        i.identifier == test_item.identifier for i in target_after_remove.items
    )
    if still_present:
        logger.error("Test item is STILL on the list after remove — remove likely failed.")
        return 1

    logger.info("CONFIRMED: test item is gone from the list after remove.")
    logger.info("=== AnyList derisking spike PASSED: auth, fetch, add, and remove all worked. ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

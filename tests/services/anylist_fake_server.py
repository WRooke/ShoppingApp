"""A stateful fake of AnyList's server for httpx.MockTransport — the test double behind the push
matrix, fault-injection and fuzz suites (Chunk 6.7, user-feedback batch; see docs/anylist-push.md > Test map).

It models what the spike and the live TestList runs actually established, NOT an idealised
server (docs/build-status/anylist-fault-finding-spike.md):

* ``add-shopping-list-item`` adds the item carried in the op's item message; adding an id that
  already exists is a silent no-op; the item's quantity (``rawQuantity``), note (details),
  name and ``checked`` flag come from the item message.
* ``set-list-item-quantity`` takes a plain ``updatedValue`` and only works for a bare number
  (or the literal "kg"/"lb" tokens); a unit-bearing or EMPTY value is a silent no-op (probe 6).
* ``remove-shopping-list-item`` only works when the item message is embedded; without it, a
  silent no-op.
* ``set-list-item-checked`` takes 'y'/'n' (live-verified 2026-10-06); any other value
  (e.g. the "1" the 2026-09-18 probe used) is a silent no-op.
* An unknown handler is ignored. Every update returns HTTP 200 whether or not it applied.

Fault injection (``post_rule`` / ``get_rule``) lets a test silently drop an op, time out, return
HTTP errors, force a 401, or serve a stale read at any chosen step. The "phone" helpers
(``phone_*``) make out-of-band edits the way a household member would on the AnyList app.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

import httpx

from app.services import anylist_client as ac
from app.services.anylist_wire import (
    _build_operation_list,  # noqa: F401  (re-exported for tests that build ops by hand)
    _decode_message,
    _field_message,
    _field_string,
    _item_to_wire,
)

LIST_ID = "L1"
_BARE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")


class FakeAnyListServer:
    def __init__(self, items=(), list_name: str = "TestList") -> None:
        self.list_name = list_name
        self.items: dict[str, dict] = {}
        self.posts: list[dict] = []  # every update POST: handler, item_id, value, has_item, applied
        self.gets = 0
        self.logins = 0
        # post_rule(n, op) -> None | "drop" | "timeout" | "401" | ("status", code)   (n is 1-based)
        self.post_rule: Callable[[int, dict], object] | None = None
        # get_rule(n) -> None | "stale" | "timeout" | ("status", code)               (n is 1-based)
        self.get_rule: Callable[[int], object] | None = None
        self._last_served: bytes | None = None
        for spec in items:
            self.phone_add(**spec) if isinstance(spec, dict) else self.phone_add(*spec)

    # --- the "phone": out-of-band edits ---------------------------------------------------

    def phone_add(self, name, qty=None, note=None, checked=False, ident=None) -> str:
        ident = ident or uuid.uuid4().hex
        self.items[ident] = {"name": name, "qty": qty, "note": note, "checked": bool(checked)}
        return ident

    def ids(self, name: str) -> list[str]:
        return [i for i, it in self.items.items() if it["name"].lower() == name.lower()]

    def phone_cross_off(self, name: str) -> None:
        for i in self.ids(name):
            self.items[i]["checked"] = True

    def phone_delete(self, name: str) -> None:
        for i in self.ids(name):
            del self.items[i]

    def phone_rename(self, name: str, new_name: str) -> None:
        for i in self.ids(name):
            self.items[i]["name"] = new_name

    def phone_set_qty(self, name: str, qty) -> None:
        for i in self.ids(name):
            self.items[i]["qty"] = qty

    # --- views for assertions -------------------------------------------------------------

    def named(self, name: str) -> list[dict]:
        return [dict(self.items[i], id=i) for i in self.ids(name)]

    def active(self, name: str) -> list[dict]:
        return [it for it in self.named(name) if not it["checked"]]

    def post_count(self, handler: str | None = None) -> int:
        return sum(1 for p in self.posts if handler is None or p["handler"] == handler)

    # --- wiring ---------------------------------------------------------------------------

    def install(self, monkeypatch):
        monkeypatch.setattr(ac.settings, "anylist_fake_mode", False, raising=False)
        monkeypatch.setattr(ac.settings, "anylist_enabled", True, raising=False)
        monkeypatch.setattr(ac.settings, "anylist_email", "user@example.com", raising=False)
        monkeypatch.setattr(ac.settings, "anylist_password", "pw", raising=False)
        monkeypatch.setattr(ac.settings, "anylist_target_list_name", self.list_name, raising=False)
        monkeypatch.setattr(ac, "_RETRY_BACKOFF_S", 0.0, raising=False)  # tests don't wait
        client = ac._RealAnyList("user@example.com", "pw")
        client._http = httpx.Client(base_url=ac.BASE_URL, transport=httpx.MockTransport(self.handler))
        monkeypatch.setattr(ac, "_instance", client, raising=False)
        return client

    # --- the HTTP handler -----------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/token":
            self.logins += 1
            return httpx.Response(200, json={"access_token": f"tok{self.logins}"})
        if path == "/data/user-data/get":
            return self._get()
        if path == "/data/shopping-lists/update":
            return self._update(request)
        return httpx.Response(404)

    def _serialise(self) -> bytes:
        parts = b""
        for ident, it in self.items.items():
            parts += _field_message(
                4,
                _item_to_wire(
                    identifier=ident, list_id=LIST_ID, name=it["name"], quantity=it["qty"],
                    details=it["note"], checked=it["checked"],
                ),
            )
        wire_list = _field_string(1, LIST_ID) + _field_string(3, self.list_name) + parts
        return _field_message(1, _field_message(1, wire_list))

    def _get(self) -> httpx.Response:
        self.gets += 1
        action = self.get_rule(self.gets) if self.get_rule else None
        if action == "timeout":
            raise httpx.ReadTimeout("injected read timeout")
        if isinstance(action, tuple) and action[0] == "status":
            return httpx.Response(action[1])
        if action == "stale" and self._last_served is not None:
            return httpx.Response(200, content=self._last_served)
        data = self._serialise()
        self._last_served = data
        return httpx.Response(200, content=data)

    @staticmethod
    def _parse_op(body: bytes) -> dict:
        marker = b'name="operations"'
        i = body.index(marker)
        start = body.index(b"\r\n\r\n", i) + 4
        end = body.index(b"\r\n--", start)
        op = _decode_message(bytes(_decode_message(body[start:end])[1][0]))
        meta = _decode_message(bytes(op[1][0]))
        out = {
            "handler": meta[2][0].decode(),
            "item_id": op[3][0].decode(),
            "value": op[4][0].decode() if 4 in op else None,
            "has_item": 6 in op,
            "item": None,
            "filename": b'filename="' in body,
        }
        if 6 in op:
            f = _decode_message(bytes(op[6][0]))
            qty = None
            if 21 in f:
                qpb = _decode_message(bytes(f[21][0]))
                qty = qpb[3][0].decode() if 3 in qpb else (qpb[1][0].decode() if 1 in qpb else None)
            out["item"] = {
                "name": f[4][0].decode() if 4 in f else None,
                "note": f[5][0].decode() if 5 in f else None,
                "checked": bool(f[6][0]) if 6 in f else False,
                "qty": qty,
            }
        return out

    def _update(self, request: httpx.Request) -> httpx.Response:
        op = self._parse_op(request.content)
        n = len(self.posts) + 1
        action = self.post_rule(n, op) if self.post_rule else None
        record = {k: op[k] for k in ("handler", "item_id", "value", "has_item")}
        record["applied"] = False
        self.posts.append(record)
        if action == "timeout":
            raise httpx.ReadTimeout("injected write timeout")
        if isinstance(action, tuple) and action[0] == "status":
            return httpx.Response(action[1])
        if action == "401":
            return httpx.Response(401)
        if op["filename"] or action == "drop":
            return httpx.Response(200, content=b"")  # 200 but nothing happened
        record["applied"] = self._apply(op)
        return httpx.Response(200, content=b"")

    def _apply(self, op: dict) -> bool:
        h, ident, value = op["handler"], op["item_id"], op["value"]
        if h == "add-shopping-list-item":
            if ident in self.items or op["item"] is None:
                return False
            it = op["item"]
            self.items[ident] = {
                "name": it["name"], "qty": it["qty"], "note": it["note"], "checked": it["checked"],
            }
            return True
        if h == "set-list-item-quantity":
            if ident in self.items and value and (_BARE_NUMBER.match(value) or value in ("kg", "lb")):
                self.items[ident]["qty"] = value
                return True
            return False
        if h == "remove-shopping-list-item":
            if op["has_item"] and ident in self.items:
                del self.items[ident]
                return True
            return False
        if h == "set-list-item-checked":
            if ident in self.items and value in ("y", "n"):
                self.items[ident]["checked"] = value == "y"
                return True
            return False
        return False

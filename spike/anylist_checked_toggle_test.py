"""Chunk 6.7 (2026-10-06): does a REAL checked-state write exist? The 2026-09-18 probe sent
``set-list-item-checked`` with ``updatedValue="1"`` and saw no change, but the reference
``anylist`` npm package (node_modules/anylist/lib/item.js:206-210) encodes a boolean as
``'y'``/``'n'`` and sends no item message — so that probe never tested the correct encoding.

If it works reliably (and without collateral damage) the push can un-cross a crossed-off item
in place instead of remove + re-add. Throwaway, TestList ONLY, cleans up after itself.

For each of REPEATS items (alternating a bare count and a unit-bearing quantity, all with a
note) it checks: add unchecked -> toggle 'y' -> re-read -> toggle 'n' -> re-read, that name,
quantity and note never change, and that a later ``set-list-item-quantity`` still works on a
bare-count item. A second variant embeds the item message in the toggle op, tried only if the
reference (no-embed) shape fails.

Usage (live; the maintainer allowed TestList-only runs on 2026-10-06):
    set ANYLIST_ENABLED=true & set ANYLIST_FAKE_MODE=false &
    .venv\\Scripts\\python.exe -m spike.anylist_checked_toggle_test
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_wire import (
    _build_operation, _build_operation_list, _decode_message, _field_bool, _field_message,
    _field_string, _item_to_wire, _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("checked_toggle")

PREFIX = "TG-"
REPEATS = 6
SETTLE = 0.5


def _retry(fn, attempts=4):
    """AnyList occasionally takes >15 s to answer; a timeout is transient, not a finding."""
    for n in range(attempts):
        try:
            return fn()
        except ac.AnyListError as exc:
            if n == attempts - 1:
                raise
            logger.warning("transient AnyList error (%s) - retry %d", exc, n + 1)
            time.sleep(2)


def post(client, op: bytes) -> None:
    _retry(lambda: client._data_post(
        "/data/shopping-lists/update",
        files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
    ))


def list_id_of(client) -> str:
    resp = client._data_post("/data/user-data/get")
    top = _decode_message(resp.content)
    inner = _decode_message(top[1][0])
    for raw_list in inner.get(1, []):
        lst = _decode_message(raw_list)
        if (_s(lst, 3) or "").strip() == settings.anylist_target_list_name.strip():
            return _s(lst, 1) or ""
    raise RuntimeError("target list not found")


def read(ident: str):
    return next((i for i in _retry(ac.get_items) if i.identifier == ident), None)


def add_item(client, list_id, name, qty, note, checked=False) -> str:
    ident = uuid.uuid4().hex
    post(client, _build_operation(
        handler_id="add-shopping-list-item", list_id=list_id, list_item_id=ident,
        item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=qty,
                                details=note, checked=checked),
    ))
    return ident


def toggle(client, list_id, ident, value: bool, embed: bool, name="", qty=None, note=None):
    post(client, _build_operation(
        handler_id="set-list-item-checked", list_id=list_id, list_item_id=ident,
        updated_value="y" if value else "n",
        item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=qty,
                                details=note, checked=value) if embed else None,
    ))


def remove_item(client, list_id, ident, name):
    post(client, _build_operation(
        handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident,
        item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None),
    ))


def run_variant(client, list_id, embed: bool, results: list, created: list):
    for rep in range(REPEATS):
        bare = rep % 2 == 0
        name, qty, note = f"{PREFIX}{'e' if embed else 'n'}{rep}", ("3" if bare else "200 g"), f"note-{rep}"
        ident = add_item(client, list_id, name, qty, note)
        created.append((ident, name))
        time.sleep(SETTLE)
        row = {"embed": embed, "rep": rep, "qty": qty}

        toggle(client, list_id, ident, True, embed, name, qty, note)
        time.sleep(SETTLE)
        a = read(ident)
        row["to_checked_ok"] = bool(a and a.checked)
        row["after_check_collateral_ok"] = bool(a and a.name == name and a.quantity == qty and a.note == note)

        toggle(client, list_id, ident, False, embed, name, qty, note)
        time.sleep(SETTLE)
        b = read(ident)
        row["to_unchecked_ok"] = bool(b and not b.checked)
        row["after_uncheck_collateral_ok"] = bool(b and b.name == name and b.quantity == qty and b.note == note)

        if bare:  # does a later quantity update still work after toggling?
            post(client, _build_operation(
                handler_id="set-list-item-quantity", list_id=list_id, list_item_id=ident,
                updated_value="7",
            ))
            time.sleep(SETTLE)
            c = read(ident)
            row["qty_update_after_toggle_ok"] = bool(c and c.quantity == "7" and not c.checked)
        # and the un-cross case that matters: an item that STARTS crossed off
        ident2 = add_item(client, list_id, name + "-x", qty, note, checked=True)
        created.append((ident2, name + "-x"))
        time.sleep(SETTLE)
        toggle(client, list_id, ident2, False, embed, name + "-x", qty, note)
        time.sleep(SETTLE)
        d = read(ident2)
        row["uncross_from_crossed_ok"] = bool(d and not d.checked and d.quantity == qty and d.note == note)
        logger.info("variant embed=%s rep=%d -> %s", embed, rep, row)
        results.append(row)


def main() -> int:
    if (settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode
            or not settings.anylist_enabled):
        logger.error("Refusing to run: target list must be TestList with ANYLIST_ENABLED=true and fake mode off.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()
    list_id = list_id_of(client)
    baseline = [(i.identifier, i.name, i.checked) for i in _retry(ac.get_items)]
    logger.info("baseline TestList: %s", [(n, bool(c)) for _i, n, c in baseline])

    results: list[dict] = []
    created: list[tuple[str, str]] = []
    try:
        run_variant(client, list_id, embed=False, results=results, created=created)
        keys = ("to_checked_ok", "to_unchecked_ok", "uncross_from_crossed_ok")
        if not all(r[k] for r in results for k in keys):
            logger.warning("no-embed variant not fully working -> trying the embedded-item-message shape")
            run_variant(client, list_id, embed=True, results=results, created=created)
    finally:
        for ident, name in created:
            try:
                remove_item(client, list_id, ident, name)
            except Exception as exc:  # noqa: BLE001
                logger.error("cleanup failed for %s: %s", name, exc)
            time.sleep(0.2)
        time.sleep(SETTLE)
        left = [(i.name, bool(i.checked)) for i in _retry(ac.get_items)]
        logger.info("TestList after cleanup: %s", left)
        base_names = sorted((n, bool(c)) for _i, n, c in baseline)
        logger.info("baseline restored: %s", sorted(left) == base_names)

    print(json.dumps(results, indent=2))
    for variant in (False, True):
        rows = [r for r in results if r["embed"] is variant]
        if not rows:
            continue
        summary = {k: f"{sum(1 for r in rows if r.get(k))}/{sum(1 for r in rows if k in r)}"
                   for k in rows[0] if k.endswith("_ok")}
        print("embed" if variant else "no-embed (reference shape)", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

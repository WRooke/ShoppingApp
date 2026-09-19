"""AnyList quantity-mechanism experiment (2026-09-19/20) — Phase 1, Stage 1A of the
"resolve the quantity bug" plan (see docs/build-status/anylist-fault-finding-spike.md).

Throwaway script. NOT wired into the app — do not import this from app/.

Tests the PR #62 hypothesis (github.com/kevdliu/anylist, formerly codetheweb/anylist — an
unmerged fix in the reference library this connector was adapted from): AnyList's apps render
`quantityPb.rawQuantity` for display, not `quantityPb.amount` alone; an item whose `amount` is
non-numeric and has no `rawQuantity` shows no quantity at all. Our connector (`anylist_wire.py`)
never sets `rawQuantity` today, on either add or update — this script builds a "v2" item wire
that does, matching PR #62's own parsing rule, and tests it across a full factorial of quantity
shape (F1) x operation (F2) x mechanism (F3) — 9 x 2 x 2 = 36 cells, one fresh item per cell so
results are never confounded by another cell's history.

Deliberately does NOT modify app/services/anylist_wire.py or anylist_client.py — this is
read-only experimentation. If Stage 1A confirms the hypothesis, Phase 3 makes the real change
there, with full offline test coverage, not this script.

Always targets settings.anylist_target_list_name (TestList) — refuses to run otherwise. Every
item is prefixed `QM-` (Quantity Mechanism). Reads credentials the same way the app does.

Usage:
    .venv\\Scripts\\python.exe -m spike.anylist_quantity_mechanism_test
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem
from app.services.anylist_wire import (
    _b,
    _build_operation,
    _build_operation_list,
    _decode_message,
    _field_bool,
    _field_message,
    _field_string,
    _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("anylist_quantity_mechanism_test")

PREFIX = "QM-"
RESULTS: list[dict] = []

# --- F1: quantity shapes -----------------------------------------------------------------
QUANTITY_SHAPES = {
    "bare_int": "5",
    "bare_decimal": "1.5",
    "int_short_unit": "500 g",
    "decimal_unit": "1.5 kg",
    "int_multiword_unit": "2 x 500g pack",
    "nonnumeric_text": "2 x bunch",
    "empty": "",
    "zero": "0",
    "large_number_unit": "123456 g",
}

# The UPDATE cell must send a genuinely DIFFERENT value than what ADD used, or a no-op update
# (server silently ignores it) is indistinguishable from a successful one -- both would leave
# the add-time value sitting there unchanged.
QUANTITY_SHAPES_UPDATE = {
    "bare_int": "7",
    "bare_decimal": "2.5",
    "int_short_unit": "600 g",
    "decimal_unit": "2.5 kg",
    "int_multiword_unit": "3 x 500g pack",
    "nonnumeric_text": "3 x bunch",
    "empty": "",  # stays empty -- no meaningful "different empty" to send
    "zero": "0",  # stays zero for the same reason
    "large_number_unit": "654321 g",
}

# PR #62's own parsing rule, reproduced exactly for this experiment.
_LEADING_NUMBER = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.*)$")


def parse_quantity_v2(raw: str) -> tuple[str | None, str | None, str | None]:
    """(rawQuantity, amount, unit) the PR #62 way. Empty input -> all None (no quantityPb at
    all, matching the current connector's `if quantity:` guard)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None, None
    m = _LEADING_NUMBER.match(raw)
    if not m:
        return raw, None, None
    amount, unit = m.group(1), m.group(2)
    return raw, amount, (unit or None)


def item_to_wire_v1(*, identifier: str, list_id: str, name: str, quantity: str) -> bytes:
    """Today's actual behaviour (mirrors anylist_wire._item_to_wire) -- amount only."""
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_bool(6, False)
    if quantity:
        out += _field_message(21, _field_string(1, quantity))
    return out


def item_to_wire_v2(*, identifier: str, list_id: str, name: str, quantity: str) -> bytes:
    """PR #62's shape -- rawQuantity + parsed amount/unit, all three sub-fields."""
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_bool(6, False)
    raw_q, amount, unit = parse_quantity_v2(quantity)
    if raw_q is not None:
        qty_pb = _field_string(3, raw_q)  # field 3 = rawQuantity
        if amount is not None:
            qty_pb += _field_string(1, amount)  # field 1 = amount
        if unit is not None:
            qty_pb += _field_string(2, unit)  # field 2 = unit
        out += _field_message(21, qty_pb)
    return out


def raw_dump() -> tuple[str, dict[str, dict]]:
    client = ac._get_client()
    resp = client._data_post("/data/user-data/get")
    top = _decode_message(resp.content)
    inner = _decode_message(top[1][0])
    for raw_list in inner.get(1, []):
        lst = _decode_message(raw_list)
        if (_s(lst, 3) or "").strip() == settings.anylist_target_list_name.strip():
            list_id = _s(lst, 1) or ""
            items = {}
            for raw_item in lst.get(4, []):
                f = _decode_message(raw_item)
                items[_s(f, 1) or ""] = f
            return list_id, items
    raise RuntimeError(f"target list {settings.anylist_target_list_name!r} not found")


def describe(f: dict) -> dict:
    has21 = 21 in f
    qty_pb = _decode_message(f[21][0]) if has21 else {}
    return {
        "f21_present": has21,
        "amount": _s(qty_pb, 1),
        "unit": _s(qty_pb, 2),
        "rawQuantity": _s(qty_pb, 3),
        "f18_deprecated": _s(f, 18),
        "note": _s(f, 5),
    }


def wire_success(desc: dict, expected_raw: str) -> bool:
    """Best-effort proxy for 'the value is present and correct at the wire level' -- catches
    the write-level wipe this connector has observed; does NOT prove the app renders it (that
    needs a phone check, flagged separately for ambiguous/ADD cells)."""
    if not expected_raw:
        return not desc["f21_present"] and not desc["f18_deprecated"]
    candidates = [desc["rawQuantity"], desc["amount"], desc["f18_deprecated"]]
    if desc["amount"] and desc["unit"]:
        candidates.append(f"{desc['amount']} {desc['unit']}")
    return expected_raw in [c for c in candidates if c]


def post_op(client, op: bytes) -> None:
    client._data_post(
        "/data/shopping-lists/update",
        files={"operations": (None, _build_operation_list([op]), "application/octet-stream")},
    )


def run_cell(shape_name: str, quantity: str, mechanism: str, list_id: str) -> None:
    """One cell each for ADD and UPDATE, sharing one freshly-added baseline item."""
    client = ac._get_client()
    name = f"{PREFIX}{shape_name}-{mechanism}"

    # --- ADD cell ---
    add_id = uuid.uuid4().hex
    build = item_to_wire_v1 if mechanism == "v1" else item_to_wire_v2
    add_wire = build(identifier=add_id, list_id=list_id, name=name, quantity=quantity)
    op = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=add_id, item_wire=add_wire)
    post_op(client, op)
    time.sleep(0.3)
    _, items = raw_dump()
    add_desc = describe(items.get(add_id, {}))
    add_ok = wire_success(add_desc, quantity)
    RESULTS.append({
        "cell": f"{shape_name}/add/{mechanism}", "shape": shape_name, "quantity": quantity,
        "op": "add", "mechanism": mechanism, "wire_ok": add_ok, "desc": add_desc,
        "needs_phone_check": True,  # ADD's wire-level "ok" can't rule out the PR #62 render bug
    })
    logger.info("ADD  shape=%-20s mech=%s wire_ok=%s desc=%s", shape_name, mechanism, add_ok, add_desc)

    # --- UPDATE cell: update the SAME item we just added, to a DIFFERENT value of the same shape
    # (so a successful update is distinguishable from the server silently ignoring it and the
    # add-time value just sitting there unchanged) ---
    updated_quantity = QUANTITY_SHAPES_UPDATE[shape_name]
    if mechanism == "v1":
        op = _build_operation(handler_id="set-list-item-quantity", list_id=list_id, list_item_id=add_id, updated_value=updated_quantity or "")
    else:
        upd_wire = item_to_wire_v2(identifier=add_id, list_id=list_id, name=name, quantity=updated_quantity)
        op = _build_operation(handler_id="set-list-item-quantity", list_id=list_id, list_item_id=add_id, item_wire=upd_wire)
    post_op(client, op)
    time.sleep(0.3)
    _, items2 = raw_dump()
    upd_desc = describe(items2.get(add_id, {}))
    upd_ok = wire_success(upd_desc, updated_quantity)
    RESULTS.append({
        "cell": f"{shape_name}/update/{mechanism}", "shape": shape_name, "quantity": updated_quantity,
        "op": "update", "mechanism": mechanism, "wire_ok": upd_ok, "desc": upd_desc,
        "needs_phone_check": upd_ok,  # only worth a phone check if the wire write succeeded at all
        "item_name": name, "item_id": add_id,
    })
    logger.info("UPD  shape=%-20s mech=%s wire_ok=%s desc=%s", shape_name, mechanism, upd_ok, upd_desc)


def main() -> int:
    if settings.anylist_target_list_name.strip() != "TestList":
        logger.error("Refusing to run: target list is %r, not TestList.", settings.anylist_target_list_name)
        return 1
    if settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: needs ANYLIST_ENABLED=true and ANYLIST_FAKE_MODE=false.")
        return 1

    ac.reset_client()
    ac.check_auth()

    list_id, _ = raw_dump()
    logger.info("=== Stage 1A: %d shapes x 2 mechanisms x (add+update), list_id=%s ===", len(QUANTITY_SHAPES), list_id)
    for shape_name, quantity in QUANTITY_SHAPES.items():
        for mechanism in ("v1", "v2"):
            try:
                run_cell(shape_name, quantity, mechanism, list_id)
            except Exception:
                logger.error("cell shape=%s mechanism=%s raised", shape_name, mechanism, exc_info=True)
            time.sleep(0.5)

    out = Path(__file__).resolve().parent / "anylist_quantity_mechanism_results.json"
    out.write_text(json.dumps(RESULTS, indent=2, default=str))

    logger.info("=== SUMMARY ===")
    for r in RESULTS:
        logger.info("%-35s wire_ok=%-5s %s", r["cell"], r["wire_ok"], r["desc"])

    phone_check_list = [r["item_name"] for r in RESULTS if r.get("needs_phone_check") and r["op"] == "update"]
    logger.info("Items worth a phone check (left on TestList, not cleaned up): %s", phone_check_list)
    logger.info("Results written to %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

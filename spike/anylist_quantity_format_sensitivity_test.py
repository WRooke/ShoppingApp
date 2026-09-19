"""AnyList update-format sensitivity follow-up (2026-09-20) — Phase 1, Stage 1C of the
"resolve the quantity bug" plan.

Stage 1A's 36-cell run found the item-wire-embed-on-update experiment (v2) is a dead end (no
better than, arguably worse than, today's plain updated_value approach: v2 succeeded on only
the trivial empty-string cell, v1 succeeded on 5 of 9). More importantly, v1's own results broke
the clean "any unit fails" pattern: `"600 g"` (int+unit) failed, but `"2.5 kg"` (decimal+unit)
SUCCEEDED — a single data point, could be a fluke or could reveal the real parsing rule. This
script repeats the ambiguous cells and probes nearby format variants (decimal-formatted
integers, no-space-before-unit, unit-before-number) to find the actual boundary, per Stage 1C's
"repeat 5-10x before concluding anything" discipline.

Throwaway script. NOT wired into the app. Refuses to run unless targeting TestList.

Usage:
    .venv\\Scripts\\python.exe -m spike.anylist_quantity_format_sensitivity_test
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path

from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("anylist_quantity_format_sensitivity_test")

PREFIX = "QF-"
RESULTS: list[dict] = []

# Each case: (label, add_value, update_value). Repeated REPEATS times each, fresh item every
# repeat, to tell a real format-boundary effect apart from one-off flakiness.
CASES = [
    ("int_space_unit", "500 g", "600 g"),        # Stage 1A: FAILED once
    ("decimal_space_unit", "1.5 kg", "2.5 kg"),  # Stage 1A: SUCCEEDED once -- the anomaly
    ("int_dotzero_space_unit", "500.0 g", "600.0 g"),   # does decimal-formatting an int help?
    ("int_nospace_unit", "500g", "600g"),        # does the space matter?
    ("decimal_nospace_unit", "1.5kg", "2.5kg"),
    ("unit_before_number", "g 500", "g 600"),    # does token order matter?
    ("bare_int_control", "5", "7"),              # control: known-good
    ("bare_decimal_control", "1.5", "2.5"),      # control: known-good (also anomalous-shape adjacent)
]
REPEATS = 6


def raw_dump() -> tuple[str, dict]:
    from app.services.anylist_wire import _decode_message, _s
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
    raise RuntimeError("target list not found")


def landed(items: dict, ident: str, expected: str) -> bool:
    from app.services.anylist_wire import _decode_message, _s
    f = items.get(ident)
    if f is None:
        return False
    if 21 in f:
        amt = _s(_decode_message(f[21][0]), 1)
        if amt == expected:
            return True
    return _s(f, 18) == expected


def run_case(label: str, add_value: str, update_value: str, rep: int) -> bool:
    name = f"{PREFIX}{label}-{rep}"
    res = ac.add_or_increment_items([PushItem(name=name, quantity=add_value)])
    if not res.added or not res.confirmed:
        logger.warning("%s rep=%d: add itself didn't confirm (%s) -- skipping update check", label, rep, res.discrepancies)
        return False
    ident = res.added_ids.get(name)
    if ident is None:
        _, items = raw_dump()
        ident = next((i for i, f in items.items() if f), None)
    time.sleep(0.2)
    res2 = ac.add_or_increment_items([PushItem(name=name, quantity=update_value, existing_id=ident)])
    ok = bool(res2.confirmed)
    logger.info("%-25s rep=%d add=%r update=%r -> confirmed=%s retried=%s", label, rep, add_value, update_value, ok, res2.retried)
    RESULTS.append({"label": label, "rep": rep, "add_value": add_value, "update_value": update_value, "confirmed": ok, "discrepancies": res2.discrepancies})
    return ok


def main() -> int:
    if settings.anylist_target_list_name.strip() != "TestList":
        logger.error("Refusing to run: target list is %r, not TestList.", settings.anylist_target_list_name)
        return 1
    if settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: needs ANYLIST_ENABLED=true and ANYLIST_FAKE_MODE=false.")
        return 1

    ac.reset_client()
    ac.check_auth()

    for label, add_value, update_value in CASES:
        for rep in range(REPEATS):
            try:
                run_case(label, add_value, update_value, rep)
            except Exception:
                logger.error("%s rep=%d raised", label, rep, exc_info=True)
            time.sleep(0.4)

    out = Path(__file__).resolve().parent / "anylist_quantity_format_sensitivity_results.json"
    out.write_text(json.dumps(RESULTS, indent=2, default=str))

    logger.info("=== SUMMARY (success rate per case) ===")
    by_label: dict[str, list[bool]] = {}
    for r in RESULTS:
        by_label.setdefault(r["label"], []).append(r["confirmed"])
    for label, outcomes in by_label.items():
        logger.info("%-25s %d/%d succeeded", label, sum(outcomes), len(outcomes))

    # cleanup
    _, items = raw_dump()
    client = ac._get_client()
    from app.services.anylist_wire import _build_operation, _build_operation_list, _item_to_wire, _s
    list_id, items = raw_dump()
    removed = 0
    for ident, f in items.items():
        name = _s(f, 4) or ""
        if name.upper().startswith(PREFIX.upper()):
            op = _build_operation(handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident,
                item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None))
            try:
                client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
                removed += 1
            except Exception:
                pass
            time.sleep(0.15)
    logger.info("cleanup: removed %d QF- items", removed)
    logger.info("Results written to %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Unit-sweep follow-up (2026-09-20): "kg" survives set-list-item-quantity updates, "g"/"ml"
don't, even with the identical decimal+space format. Tests whether this is a "major metric
unit" pattern (kg, L) vs "minor/subdivision unit" pattern (g, ml, mg), or something else
entirely, by sweeping a broader set of common recipe/grocery units. Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_quantity_unit_sweep
"""
from __future__ import annotations
import json, logging, sys, time
from pathlib import Path
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("unit_sweep")

PREFIX = "QU-"
# (label, unit) -- always "1.5 <unit>" -> "2.5 <unit>", the one confirmed-working shape for kg.
UNITS = ["kg", "L", "lb", "oz", "cup", "tbsp", "tsp", "g", "ml", "mg", "mL", "Kg", "litre", "pack"]
REPEATS = 3
RESULTS = []


def run_case(unit, rep):
    label = f"unit_{unit}"
    name = f"{PREFIX}{label}-{rep}"
    add_value, update_value = f"1.5 {unit}", f"2.5 {unit}"
    res = ac.add_or_increment_items([PushItem(name=name, quantity=add_value)])
    if not res.added or not res.confirmed:
        logger.warning("%s rep=%d: add didn't confirm", label, rep)
        return
    ident = res.added_ids.get(name)
    time.sleep(0.2)
    res2 = ac.add_or_increment_items([PushItem(name=name, quantity=update_value, existing_id=ident)])
    logger.info("%-15s rep=%d confirmed=%s", unit, rep, res2.confirmed)
    RESULTS.append({"unit": unit, "rep": rep, "confirmed": bool(res2.confirmed)})


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    for unit in UNITS:
        for rep in range(REPEATS):
            try:
                run_case(unit, rep)
            except Exception:
                logger.error("unit=%s rep=%d raised", unit, rep, exc_info=True)
            time.sleep(0.4)

    out = Path(__file__).resolve().parent / "anylist_quantity_unit_sweep_results.json"
    out.write_text(json.dumps(RESULTS, indent=2))

    by_unit = {}
    for r in RESULTS:
        by_unit.setdefault(r["unit"], []).append(r["confirmed"])
    logger.info("=== SUMMARY ===")
    for unit, outcomes in by_unit.items():
        logger.info("%-15s %d/%d succeeded", unit, sum(outcomes), len(outcomes))

    from app.services.anylist_wire import _build_operation, _build_operation_list, _item_to_wire, _decode_message, _s
    client = ac._get_client()
    resp = client._data_post("/data/user-data/get")
    top = _decode_message(resp.content)
    inner = _decode_message(top[1][0])
    list_id, items = "", {}
    for raw_list in inner.get(1, []):
        lst = _decode_message(raw_list)
        if (_s(lst, 3) or "").strip() == settings.anylist_target_list_name.strip():
            list_id = _s(lst, 1) or ""
            for raw_item in lst.get(4, []):
                f = _decode_message(raw_item)
                items[_s(f, 1) or ""] = f
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
    logger.info("cleanup: removed %d QU- items", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

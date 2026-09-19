"""Final confirmatory round for the quantity-format finding (2026-09-20). Isolates whether
"decimal + space + unit" succeeding on update is about the NUMBER format (unit-independent) or
specific to "kg" (the only unit tested so far in that combination). Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_quantity_format_confirm
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
logger = logging.getLogger("confirm")

PREFIX = "QC-"
CASES = [
    ("decimal_space_g", "1.5 g", "2.5 g"),          # decimal+space+"g" (not kg) -- isolates unit
    ("decimal_space_g_large", "600.5 g", "700.5 g"),  # decimal w/ 3-digit whole part + space + g
    ("decimal_space_ml", "1.5 ml", "2.5 ml"),        # decimal+space+ml, a 3rd unit
]
REPEATS = 6
RESULTS = []


def run_case(label, add_value, update_value, rep):
    name = f"{PREFIX}{label}-{rep}"
    res = ac.add_or_increment_items([PushItem(name=name, quantity=add_value)])
    if not res.added or not res.confirmed:
        logger.warning("%s rep=%d: add didn't confirm", label, rep)
        return
    ident = res.added_ids.get(name)
    time.sleep(0.2)
    res2 = ac.add_or_increment_items([PushItem(name=name, quantity=update_value, existing_id=ident)])
    logger.info("%-25s rep=%d %r->%r confirmed=%s", label, rep, add_value, update_value, res2.confirmed)
    RESULTS.append({"label": label, "rep": rep, "add": add_value, "update": update_value, "confirmed": bool(res2.confirmed)})


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
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

    out = Path(__file__).resolve().parent / "anylist_quantity_format_confirm_results.json"
    out.write_text(json.dumps(RESULTS, indent=2))

    by_label = {}
    for r in RESULTS:
        by_label.setdefault(r["label"], []).append(r["confirmed"])
    logger.info("=== SUMMARY ===")
    for label, outcomes in by_label.items():
        logger.info("%-25s %d/%d succeeded", label, sum(outcomes), len(outcomes))

    # cleanup
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
    logger.info("cleanup: removed %d QC- items", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

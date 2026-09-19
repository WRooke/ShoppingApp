"""Does set-list-item-name have the same update-reliability problem as set-list-item-quantity?
Directly relevant to candidate strategy 2 (fold the unit into the item name) -- if renaming an
existing item is itself unreliable, that strategy is built on sand. Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_name_update_test
"""
from __future__ import annotations
import json, logging, sys, time
from pathlib import Path
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem
from app.services.anylist_wire import _build_operation, _build_operation_list, _decode_message, _s

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("name_update_test")

PREFIX = "QN-"
REPEATS = 8
RESULTS = []


def raw_dump():
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
    raise RuntimeError("not found")


def run_rep(rep: int):
    client = ac._get_client()
    old_name = f"{PREFIX}before-{rep}"
    new_name = f"{PREFIX}after-{rep}"
    res = ac.add_or_increment_items([PushItem(name=old_name, quantity="1")])
    if not res.added or not res.confirmed:
        logger.warning("rep=%d: add didn't confirm", rep)
        return
    ident = res.added_ids.get(old_name)
    time.sleep(0.2)
    list_id, _ = raw_dump()
    op = _build_operation(handler_id="set-list-item-name", list_id=list_id, list_item_id=ident, updated_value=new_name)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
    time.sleep(0.3)
    _, items = raw_dump()
    got_name = _s(items.get(ident, {}), 4)
    ok = got_name == new_name
    logger.info("rep=%d rename %r -> %r: got %r ok=%s", rep, old_name, new_name, got_name, ok)
    RESULTS.append({"rep": rep, "old": old_name, "new": new_name, "got": got_name, "ok": ok})


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    for rep in range(REPEATS):
        try:
            run_rep(rep)
        except Exception:
            logger.error("rep=%d raised", rep, exc_info=True)
        time.sleep(0.4)

    out = Path(__file__).resolve().parent / "anylist_name_update_results.json"
    out.write_text(json.dumps(RESULTS, indent=2))
    oks = [r["ok"] for r in RESULTS]
    logger.info("=== SUMMARY: %d/%d renames succeeded ===", sum(oks), len(oks))

    from app.services.anylist_wire import _item_to_wire
    client = ac._get_client()
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
    logger.info("cleanup: removed %d QN- items", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

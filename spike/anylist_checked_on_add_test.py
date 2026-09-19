"""Phase B step 1 (2026-09-20): does add-shopping-list-item with checked=true in the item
message actually land as checked on re-fetch? Every ADD tested so far in this investigation has
used checked=false -- this specific case is untested and load-bearing for the lossless
delete+re-add design (it needs to preserve a checked item's checked state across the cycle).
Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_checked_on_add_test
"""
from __future__ import annotations
import json, logging, sys, time, uuid
from pathlib import Path
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_wire import (
    _b, _build_operation, _build_operation_list, _decode_message, _field_bool, _field_message,
    _field_string, _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("checked_on_add")

PREFIX = "CK-"
REPEATS = 6
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


def add_checked_item(client, list_id, name, checked, note):
    ident = uuid.uuid4().hex
    wire = (
        _field_string(1, ident) + _field_string(3, list_id) + _field_string(4, name)
        + _field_string(5, note) + _field_bool(6, checked)
        + _field_message(21, _field_string(3, "3") + _field_string(1, "3"))
    )
    op = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=ident, item_wire=wire)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
    return ident


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()
    list_id, _ = raw_dump()

    for rep in range(REPEATS):
        name = f"{PREFIX}checked-{rep}"
        note = f"note-{rep}"
        ident = add_checked_item(client, list_id, name, True, note)
        time.sleep(0.3)
        _, items = raw_dump()
        f = items.get(ident)
        checked = _b(f, 6) if f else None
        got_note = _s(f, 5) if f else None
        ok = checked is True and got_note == note
        logger.info("rep=%d checked=%r note=%r ok=%s", rep, checked, got_note, ok)
        RESULTS.append({"rep": rep, "checked": checked, "note": got_note, "ok": ok})
        time.sleep(0.4)

    out = Path(__file__).resolve().parent / "anylist_checked_on_add_results.json"
    out.write_text(json.dumps(RESULTS, indent=2))
    oks = [r["ok"] for r in RESULTS]
    logger.info("=== SUMMARY: %d/%d succeeded (checked=true AND note both landed on add) ===", sum(oks), len(oks))

    from app.services.anylist_wire import _item_to_wire
    _, items = raw_dump()
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
    logger.info("cleanup: removed %d CK- items", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

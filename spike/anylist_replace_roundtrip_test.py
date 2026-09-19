"""Phase B step 4 (2026-09-20): live proof that the "replace" mechanism actually preserves
checked-state and notes through a unit-bearing quantity change, against the real API -- not
just the offline mocked tests. Drives the REAL production connector
(app.services.anylist_client), same as every other live check this investigation has done.

Simulates: this week's push (a fresh add), the household manually checking the item off in the
AnyList app (simulated here via a direct wire op, standing in for a person tapping it), then
next week's push with a different unit-bearing amount (the "replace" path) -- and confirms
quantity, note, AND checked all come through intact. Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_replace_roundtrip_test
"""
from __future__ import annotations
import logging, sys, time, uuid
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_client import PushItem
from app.services.anylist_wire import (
    _build_operation, _build_operation_list, _decode_message, _item_to_wire, _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("replace_roundtrip")

NAME = "REPLACE-ROUNDTRIP-Flour"


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


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()

    # "This week": fresh add, unit-bearing quantity, a note, AND checked=True -- standing in
    # for an item a household member already ticked off, using the mechanism already
    # live-confirmed reliable (6/6, spike/anylist_checked_on_add_test.py) rather than the
    # still-unconfirmed "set-list-item-checked" handler guess from the 2026-09-19 spike.
    list_id, _ = raw_dump()
    item_id = uuid.uuid4().hex
    wire = _item_to_wire(
        identifier=item_id, list_id=list_id, name=NAME, quantity="500 g",
        details="Original note", checked=True,
    )
    op = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=item_id, item_wire=wire)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
    time.sleep(0.3)
    from app.services.anylist_wire import _b
    _, items = raw_dump()
    checked_before = _b(items.get(item_id, {}), 6)
    logger.info("Added %r id=%s quantity='500 g' note='Original note' checked=%r", NAME, item_id, checked_before)
    assert checked_before is True, "setup failed -- the item wasn't actually checked, can't test preservation"

    # "Next week": different unit-bearing amount -> goes through the replace path.
    res2 = ac.add_or_increment_items([PushItem(name=NAME, quantity="750 g", existing_id=item_id, note="Updated note")])
    assert res2.confirmed, res2
    new_id = res2.added_ids.get(NAME)
    logger.info("Replaced -> new id=%s (old was %s)", new_id, item_id)
    assert new_id and new_id != item_id

    final = next(i for i in ac.get_items() if i.name == NAME)
    logger.info(
        "FINAL: identifier=%s quantity=%r note=%r checked=%r",
        final.identifier, final.quantity, final.note, final.checked,
    )
    ok_qty = final.quantity == "750 g"
    ok_note = final.note == "Updated note"
    ok_checked = final.checked is True
    logger.info("quantity_ok=%s note_ok=%s checked_ok=%s", ok_qty, ok_note, ok_checked)
    logger.info("Left on TestList as %r for a phone check.", NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())

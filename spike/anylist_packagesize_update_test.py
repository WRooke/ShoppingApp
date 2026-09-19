"""Phase A step 2 (2026-09-20): packageSizePb.rawPackageSize was just phone-confirmed to
display on AnyList's main list view exactly like a normal quantity chip -- a genuinely new
lead. This tests whether it can be UPDATED reliably, unlike quantityPb/deprecatedQuantity.

No handler for packageSizePb exists anywhere in the reference library (checked
lib/definitions.json and every .js file -- only name/quantity/details/checked/
categoryMatchId/manualSortIndex have known handlers), so this tries a few plausible
approaches and measures each across repeats before trusting any result. Throwaway,
TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_packagesize_update_test
"""
from __future__ import annotations
import json, logging, sys, time, uuid
from pathlib import Path
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_wire import (
    _build_operation, _build_operation_list, _decode_message, _field_bool, _field_message,
    _field_string, _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("packagesize_update")

PREFIX = "PS-"
REPEATS = 4
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


def package_size_msg(raw: str, size: str | None = None, unit: str | None = None) -> bytes:
    out = _field_string(3, raw)
    if size is not None:
        out += _field_string(1, size)
    if unit is not None:
        out += _field_string(2, unit)
    return out


def add_item(client, list_id, name, raw_package_size):
    ident = uuid.uuid4().hex
    wire = (
        _field_string(1, ident) + _field_string(3, list_id) + _field_string(4, name)
        + _field_bool(6, False) + _field_message(24, package_size_msg(raw_package_size, "1", "pack"))
    )
    op = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=ident, item_wire=wire)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
    return ident


def landed(items, ident, expected_raw):
    f = items.get(ident)
    if f is None or 24 not in f:
        return False
    ps = _decode_message(f[24][0])
    return _s(ps, 4) == expected_raw


def try_approach(client, list_id, label, rep, build_op):
    name = f"{PREFIX}{label}-{rep}"
    ident = add_item(client, list_id, name, "1 x A")
    time.sleep(0.2)
    op = build_op(list_id, ident, "2 x B")
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
    time.sleep(0.3)
    _, items = raw_dump()
    ok = landed(items, ident, "2 x B")
    logger.info("%-30s rep=%d landed=%s", label, rep, ok)
    RESULTS.append({"label": label, "rep": rep, "landed": ok})
    return ident


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()
    list_id, _ = raw_dump()

    approaches = {
        "guessed-handler-flat-value": lambda lid, ident, new_raw: _build_operation(
            handler_id="set-list-item-package-size", list_id=lid, list_item_id=ident, updated_value=new_raw,
        ),
        "guessed-handler-item-embed": lambda lid, ident, new_raw: _build_operation(
            handler_id="set-list-item-package-size", list_id=lid, list_item_id=ident,
            item_wire=_field_string(1, ident) + _field_string(3, lid) + _field_message(24, package_size_msg(new_raw, "2", "pack")),
        ),
        "quantity-handler-item-embed": lambda lid, ident, new_raw: _build_operation(
            handler_id="set-list-item-quantity", list_id=lid, list_item_id=ident,
            item_wire=_field_string(1, ident) + _field_string(3, lid) + _field_message(24, package_size_msg(new_raw, "2", "pack")),
        ),
    }

    all_items = []
    for label, build_op in approaches.items():
        for rep in range(REPEATS):
            try:
                ident = try_approach(client, list_id, label, rep, build_op)
                all_items.append((f"{PREFIX}{label}-{rep}", ident))
            except Exception:
                logger.error("%s rep=%d raised", label, rep, exc_info=True)
            time.sleep(0.4)

    out = Path(__file__).resolve().parent / "anylist_packagesize_update_results.json"
    out.write_text(json.dumps(RESULTS, indent=2))

    by_label = {}
    for r in RESULTS:
        by_label.setdefault(r["label"], []).append(r["landed"])
    logger.info("=== SUMMARY ===")
    any_success = False
    for label, outcomes in by_label.items():
        logger.info("%-30s %d/%d landed", label, sum(outcomes), len(outcomes))
        if any(outcomes):
            any_success = True

    from app.services.anylist_wire import _item_to_wire
    removed = 0
    _, items = raw_dump()
    for ident, f in items.items():
        name = _s(f, 4) or ""
        if name.upper().startswith(PREFIX.upper()):
            if any_success:
                logger.info("Leaving %r on TestList (a landed case exists) for phone check", name)
                continue
            op = _build_operation(handler_id="remove-shopping-list-item", list_id=list_id, list_item_id=ident,
                item_wire=_item_to_wire(identifier=ident, list_id=list_id, name=name, quantity=None))
            try:
                client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op]), "application/octet-stream")})
                removed += 1
            except Exception:
                pass
            time.sleep(0.15)
    logger.info("cleanup: removed=%d (left everything if any approach succeeded)", removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

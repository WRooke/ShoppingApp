"""Phase A of the "investigate unexplored fields" plan (2026-09-20) — does packageSizePb or
priceQuantityPb affect what AnyList's app actually displays, before investing in testing their
update reliability? Throwaway, TestList only.

Usage: .venv\\Scripts\\python.exe -m spike.anylist_unexplored_fields_test
"""
from __future__ import annotations
import logging, sys
from app.config import settings
from app.services import anylist_client as ac
from app.services.anylist_wire import (
    _build_operation, _build_operation_list, _decode_message, _field_bool, _field_message,
    _field_string, _s,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("unexplored_fields")

PREFIX = "UF-"


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


def package_size_message(size: str, unit: str, package_type: str, raw: str) -> bytes:
    """PBItemPackageSize: size=1, unit=2, packageType=3, rawPackageSize=4."""
    return (
        _field_string(1, size) + _field_string(2, unit)
        + _field_string(3, package_type) + _field_string(4, raw)
    )


def item_wire_with_package_size(identifier, list_id, name, package_size_bytes) -> bytes:
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_bool(6, False)
    out += _field_message(24, package_size_bytes)  # ListItem.packageSizePb, field 24
    return out


def item_wire_with_price_quantity(identifier, list_id, name, quantity_str) -> bytes:
    out = _field_string(1, identifier) + _field_string(3, list_id) + _field_string(4, name)
    out += _field_bool(6, False)
    # PBItemQuantity shape (amount=1, unit=2, rawQuantity=3), same as quantityPb, but this
    # time on ListItem.priceQuantityPb (field 22) instead of quantityPb (field 21).
    qty_pb = _field_string(3, quantity_str) + _field_string(1, "500") + _field_string(2, "g")
    out += _field_message(22, qty_pb)
    return out


def main():
    if settings.anylist_target_list_name.strip() != "TestList" or settings.anylist_fake_mode or not settings.anylist_enabled:
        logger.error("Refusing to run: wrong target/mode.")
        return 1
    ac.reset_client()
    ac.check_auth()
    client = ac._get_client()
    list_id, _ = raw_dump()

    # Item 1: packageSizePb set ("2 x 500g pack" style), NO quantityPb at all -- isolates
    # whether packageSizePb alone produces any visible display.
    id1 = "uf-packagesize-only"
    wire1 = item_wire_with_package_size(
        id1, list_id, f"{PREFIX}PackageSizeOnly",
        package_size_message("2", "500g", "pack", "2 x 500g pack"),
    )
    op1 = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=id1, item_wire=wire1)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op1]), "application/octet-stream")})

    # Item 2: priceQuantityPb set, no quantityPb -- isolates whether it shows anything.
    id2 = "uf-pricequantity-only"
    wire2 = item_wire_with_price_quantity(id2, list_id, f"{PREFIX}PriceQuantityOnly", "500 g")
    op2 = _build_operation(handler_id="add-shopping-list-item", list_id=list_id, list_item_id=id2, item_wire=wire2)
    client._data_post("/data/shopping-lists/update", files={"operations": (None, _build_operation_list([op2]), "application/octet-stream")})

    _, items = raw_dump()
    for ident, name in ((id1, f"{PREFIX}PackageSizeOnly"), (id2, f"{PREFIX}PriceQuantityOnly")):
        f = items.get(ident)
        if f is None:
            logger.warning("%s: not found after add!", name)
            continue
        logger.info("%s: raw fields present = %s", name, sorted(f.keys()))
        if 24 in f:
            ps = _decode_message(f[24][0])
            logger.info("  packageSizePb: size=%r unit=%r type=%r raw=%r", _s(ps,1), _s(ps,2), _s(ps,3), _s(ps,4))
        if 22 in f:
            pq = _decode_message(f[22][0])
            logger.info("  priceQuantityPb: amount=%r unit=%r raw=%r", _s(pq,1), _s(pq,2), _s(pq,3))

    logger.info("Both items left on TestList for a phone check: %s, %s", f"{PREFIX}PackageSizeOnly", f"{PREFIX}PriceQuantityOnly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

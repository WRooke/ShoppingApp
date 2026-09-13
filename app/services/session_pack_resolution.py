"""Purchase-pack resolution for one consolidated session item — split out of
``services/session_consolidation.py`` (2026-09-13 code review) per CLAUDE.md > Code
Architecture > File size and scope discipline. Sits alongside ``purchase_units.py``: this
module is the DB-shaped adapter (matching a `ConsolidatedItem`'s dimension/unit against a
household's own `ProductUnit` pack rows and rendering the result back into display text);
`purchase_units.py` is the pure count-the-packs arithmetic underneath it.

See CLAUDE.md > Scaling Logic > Purchase unit resolution.
"""

from __future__ import annotations

from app.models.catalog import ProductUnit
from app.services import consolidation, purchase_units

# Pack-unit strings we know how to normalise, grouped by dimension — mirrors
# consolidation._G_PER / _ML_PER so pack sizes line up with consolidated quantities.
_PACK_G = {"g": 1.0, "kg": 1000.0}
_PACK_ML = {"ml": 1.0, "l": 1000.0, "tsp": 5.0, "tbsp": 20.0, "cup": 250.0}
_PACK_COUNT = {"each", "ea", "unit", "count", ""}


def pack_options_for(
    item: consolidation.ConsolidatedItem, rows: list[ProductUnit]
) -> tuple[float, list[purchase_units.PackOption], str]:
    """(required_in_base, [PackOption in the same base], base_kind). base_kind is
    'mass' | 'volume' | 'count' | 'unit:<x>'. Rows whose unit doesn't match the item's
    dimension are dropped."""
    unit = (item.unit or "").strip().lower()
    if unit in _PACK_G or unit in ("g", "kg"):
        base_kind, factor = "mass", (1000.0 if unit == "kg" else 1.0)
        required = (item.quantity or 0.0) * factor
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty * _PACK_G[(r.purchase_unit or "").lower()])
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_G
        ]
        return required, opts, base_kind
    if unit in _PACK_ML:
        base_kind = "volume"
        required = (item.quantity or 0.0) * _PACK_ML[unit]
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty * _PACK_ML[(r.purchase_unit or "").lower()])
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_ML
        ]
        return required, opts, base_kind
    if item.unit is None:  # bare count
        required = item.quantity or 0.0
        opts = [
            purchase_units.PackOption(r.purchase_label, r.purchase_qty)
            for r in rows
            if (r.purchase_unit or "").lower() in _PACK_COUNT
        ]
        return required, opts, "count"
    # free-text unit — only match pack rows carrying the same unit string
    required = item.quantity or 0.0
    opts = [
        purchase_units.PackOption(r.purchase_label, r.purchase_qty)
        for r in rows
        if (r.purchase_unit or "").lower() == unit
    ]
    return required, opts, f"unit:{unit}"


def overage_note(overage_base: float, item: consolidation.ConsolidatedItem) -> str:
    """overage is in the consolidation base (g/ml/count); render it in the item's unit."""
    u = (item.unit or "").strip().lower()
    if u == "kg":
        return f"{consolidation._fmt_qty(overage_base / 1000)} kg spare"
    if u == "l":
        return f"{consolidation._fmt_qty(overage_base / 1000)} L spare"
    if u in ("g", "ml"):
        return f"{consolidation._fmt_qty(overage_base)} {u} spare"
    if item.unit is None:
        return f"{consolidation._fmt_qty(overage_base)} spare"
    return f"{consolidation._fmt_qty(overage_base)} {item.unit} spare"

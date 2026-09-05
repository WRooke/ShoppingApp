"""Starter data for the reference catalogue.

Phase 1 defines the data and an idempotent ``seed_reference_data`` helper but
does NOT call it. Wiring the seed into first-run startup is a Phase 2
deliverable (see CLAUDE.md > Build Phases > Phase 2).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.catalog import ProductUnit, Staple

logger = logging.getLogger(__name__)

# Australian common grocery pack sizes. Marked is_preseeded=1 on insert.
PRODUCT_UNIT_SEEDS: list[dict] = [
    # Dairy & eggs
    {"ingredient_name": "eggs", "purchase_label": "dozen", "purchase_qty": 12, "purchase_unit": "each"},
    {"ingredient_name": "milk", "purchase_label": "2L bottle", "purchase_qty": 2, "purchase_unit": "L"},
    {"ingredient_name": "butter", "purchase_label": "250g block", "purchase_qty": 250, "purchase_unit": "g"},
    {"ingredient_name": "cream", "purchase_label": "300ml carton", "purchase_qty": 300, "purchase_unit": "ml"},
    {"ingredient_name": "sour cream", "purchase_label": "200g tub", "purchase_qty": 200, "purchase_unit": "g"},
    # Meat
    {"ingredient_name": "beef mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "pork mince", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken breast", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "chicken thigh", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "bacon", "purchase_label": "175g pack", "purchase_qty": 175, "purchase_unit": "g"},
    # Pantry
    {"ingredient_name": "plain flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "self-raising flour", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "white sugar", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "brown sugar", "purchase_label": "500g bag", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "basmati rice", "purchase_label": "1kg bag", "purchase_qty": 1000, "purchase_unit": "g"},
    {"ingredient_name": "pasta", "purchase_label": "500g pack", "purchase_qty": 500, "purchase_unit": "g"},
    {"ingredient_name": "diced tomatoes", "purchase_label": "400g can", "purchase_qty": 400, "purchase_unit": "g"},
    {"ingredient_name": "coconut cream", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "coconut milk", "purchase_label": "400ml can", "purchase_qty": 400, "purchase_unit": "ml"},
    {"ingredient_name": "chicken stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
    {"ingredient_name": "beef stock", "purchase_label": "1L carton", "purchase_qty": 1000, "purchase_unit": "ml"},
]

SECTION_VOCABULARY: list[str] = [
    # Canonical, fixed, store-independent section vocabulary (Shop Layout Reorganisation
    # addendum). Not a DB table — store_sections.section_name and product_sections.section_name
    # are free text, but the UI should only offer these. Starter list; confirm/adjust with the
    # household before the store setup + capture-time section-suggestion UI is built.
    "produce",
    "dairy",
    "meat & seafood",
    "bakery",
    "frozen",
    "pantry",
    "household",
    "deli",
    "drinks",
    "other",
]

# Deliberately minimal (confirmed 2026-09-05 — see CLAUDE.md > Staples Starter List). Earlier
# draft over-seeded this with anything vaguely pantry-shaped (soy sauce, vinegars, dried
# herbs/spices, tomato paste, dijon mustard, garlic) without confirming any of it actually
# matched what this household treats as "assume we have it, don't put it on the list". Add
# more here (or via Settings, once Chunk 2.5 exists) only as real recipes surface a genuine
# staple gap — do not pre-guess the rest of the list.
STAPLE_SEEDS: list[str] = [
    "salt",
    "black pepper",
    "olive oil",
    "vegetable oil",
    "plain flour",
]


def seed_reference_data(db: Session) -> dict:
    """Insert any missing preseeded product units and staples. Idempotent.

    Returns a small dict summarising how many rows were added.
    """
    added_units = 0
    for row in PRODUCT_UNIT_SEEDS:
        exists = (
            db.query(ProductUnit)
            .filter(ProductUnit.ingredient_name == row["ingredient_name"])
            .first()
        )
        if exists is None:
            db.add(ProductUnit(is_preseeded=True, **row))
            added_units += 1

    added_staples = 0
    for name in STAPLE_SEEDS:
        exists = db.query(Staple).filter(Staple.name == name).first()
        if exists is None:
            db.add(Staple(name=name))
            added_staples += 1

    db.commit()
    result = {"product_units_added": added_units, "staples_added": added_staples}
    logger.info("Reference data seed: %s", result)
    return result

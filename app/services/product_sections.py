"""``product_sections`` write helper — used by the recipe-capture confirm step to record
AI-suggested sections. See CLAUDE.md > Shopping List Store Layout and > Recipe Capture — AI
Extraction. Plain Python / SQLAlchemy only, no `fastapi` import — see CLAUDE.md > Code
Architecture & Maintainability.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.store import ProductSection

logger = logging.getLogger(__name__)


def tag_suggested_sections(db: Session, ingredient_sections: dict[str, str]) -> int:
    """For each (ingredient_name, section_name) pair, writes a `product_sections` row with
    `source='ai_suggested'` — but only for ingredients with no existing tag yet. Never
    overwrites an existing row, whatever its source: a `user_confirmed`/`user_corrected`
    mapping is deliberate and must not be clobbered by a later capture, and an earlier
    `ai_suggested` row from a previous capture is left as first-written rather than churned
    on every new recipe that mentions the same ingredient. Returns the number of rows added.

    `ingredient_sections` keys must already be normalised (lowercase, matching
    `recipe_ingredients.name` — see CLAUDE.md > Ingredient Normalisation); this function does
    not normalise them itself.
    """
    if not ingredient_sections:
        return 0

    existing = {
        row.ingredient_name
        for row in db.query(ProductSection.ingredient_name)
        .filter(ProductSection.ingredient_name.in_(ingredient_sections.keys()))
        .all()
    }

    added = 0
    for name, section in ingredient_sections.items():
        if name in existing:
            continue
        db.add(ProductSection(ingredient_name=name, section_name=section, source="ai_suggested"))
        added += 1

    if added:
        db.commit()
        logger.info("product_sections: %d new ai_suggested tag(s) written", added)
    return added

"""``recipes`` and ``recipe_ingredients`` tables."""

from __future__ import annotations

import json

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base, utcnow


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)  # 'url' | 'photo' | 'manual'
    source_url = Column(Text, nullable=True)
    source_image_path = Column(Text, nullable=True)
    base_servings = Column(Integer, nullable=False, default=4)

    # --- source provenance (Chunk 3.7) ------------------------------------
    # Where the recipe ORIGINALLY came from, in a human-meaningful form. Orthogonal to
    # source_type (which records how the ingredients got INTO the app): a photographed or
    # hand-typed recipe can still cite a book, and a URL recipe can too. Not mutually
    # exclusive with source_url and not enforced as such. source_page is Text, not Integer,
    # so "142-143", "142 & 145", "ch. 3" all work. See CLAUDE.md > Data Model > recipes and
    # > Build Phases > Phase 3 > Chunk 3.7.
    source_book = Column(Text, nullable=True)  # e.g. "Ottolenghi SIMPLE"
    source_page = Column(Text, nullable=True)  # e.g. "142" or "142-143"

    notes = Column(Text, nullable=True)  # single freeform notes field (see CLAUDE.md > Data Model)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # --- recipe history (Schema & Planning Addendum #2) ---------------------
    times_made = Column(Integer, nullable=False, default=0)
    last_made_at = Column(DateTime, nullable=True)
    rating = Column(Text, nullable=True)  # 'up' | 'down' | null=unrated (tri-state, not 5-star)

    # --- "suggest something" schema prep (Addendum #3) — fields only, no logic yet ---
    cuisine = Column(Text, nullable=True)
    protein = Column(Text, nullable=True)

    # --- soft-delete (Addendum #5) ------------------------------------------
    archived_at = Column(DateTime, nullable=True)  # set instead of hard-deleting

    # --- AI capture status (Phase 3.9 M6) ---------------------------------
    # JSON array of still-outstanding AI capture sub-tasks (currently only
    # ["suggest_sections"] — see capture_queue). NULL / "[]" => nothing pending.
    ai_tasks_pending = Column(Text, nullable=True)

    ingredients = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.sort_order",
    )

    @property
    def ai_pending_tasks(self) -> list[str]:
        """Parsed ai_tasks_pending, always a list (never None) so callers/schemas don't
        each re-implement the json.loads + fallback."""
        if not self.ai_tasks_pending:
            return []
        try:
            value = json.loads(self.ai_tasks_pending)
            return [str(v) for v in value] if isinstance(value, list) else []
        except (ValueError, TypeError):
            return []


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(Text, nullable=False)  # normalised lowercase, e.g. "beef mince" — the ORIGINAL
    quantity = Column(Float, nullable=False)
    unit = Column(Text, nullable=True)  # null for unitless items (eggs, onions)
    preparation = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    # Substitution (Phase 3.9 M4). The swap THIS recipe uses, set only by explicit per-recipe
    # confirmation (capture review / recipe editor). NULL = no substitution, use `name`.
    # Clearing it reverts. Consolidation reads resolved_ingredient (fallback `name`).
    resolved_ingredient = Column(Text, nullable=True)
    substitution_note = Column(Text, nullable=True)
    # Substitution quantity/unit transform (Phase 3.9 M8 — see CLAUDE.md > AI Provider
    # Migration > Ingredient Substitution Flagging, and > Scaling Logic > Consolidation across
    # recipes). The ABSOLUTE amount this recipe's swap actually buys, e.g. "2 whole corn cobs"
    # -> resolved "canned corn" at 2 / "can". Only meaningful alongside resolved_ingredient;
    # both NULL => name-only swap, keep this row's own quantity/unit. When set, consolidation
    # scales (resolved_quantity, resolved_unit) instead of (quantity, unit). Clearing
    # resolved_ingredient clears these too. No cross-unit conversion is attempted — the number
    # the user entered IS the equivalence.
    resolved_quantity = Column(Float, nullable=True)
    resolved_unit = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    recipe = relationship("Recipe", back_populates="ingredients")

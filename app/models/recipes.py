"""``recipes`` and ``recipe_ingredients`` tables."""

from __future__ import annotations

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

    ingredients = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.sort_order",
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(Text, nullable=False)  # normalised lowercase, e.g. "beef mince"
    quantity = Column(Float, nullable=False)
    unit = Column(Text, nullable=True)  # null for unitless items (eggs, onions)
    preparation = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    recipe = relationship("Recipe", back_populates="ingredients")

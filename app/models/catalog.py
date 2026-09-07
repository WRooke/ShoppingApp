"""``product_units``, ``staples`` and ``remembered_substitutions`` — the editable
reference catalogue managed from the Settings page. (``remembered_substitutions`` was
``ingredient_substitutions`` with an auto-applying ``is_default`` until Phase 3.9 M4.)"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text, UniqueConstraint

from app.database import Base, utcnow


class ProductUnit(Base):
    __tablename__ = "product_units"
    # Phase 4 (Chunk 4.1): an ingredient can be sold in more than one pack size, so the
    # uniqueness moved from ``ingredient_name`` alone to (ingredient_name, purchase_label).
    # See CLAUDE.md > Data Model > product_units and > Scaling Logic > Purchase unit resolution.
    __table_args__ = (
        UniqueConstraint(
            "ingredient_name", "purchase_label", name="uq_product_unit_ingredient_label"
        ),
    )

    id = Column(Integer, primary_key=True)
    ingredient_name = Column(Text, nullable=False)  # matches recipe_ingredients.name
    purchase_label = Column(Text, nullable=False)  # e.g. "dozen", "500g pack"
    purchase_qty = Column(Float, nullable=False)
    purchase_unit = Column(Text, nullable=True)  # e.g. "g", "L", "each"
    notes = Column(Text, nullable=True)
    is_preseeded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Staple(Base):
    __tablename__ = "staples"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class UsualItem(Base):
    """"The usuals" (Phase 5 Chunk 5.4) — recurring non-recipe household items bought on a
    day-based schedule, independent of meal planning. Distinct from ``Staple`` (recipe
    ingredients assumed on-hand). Surfaced on the checklist as its own group only when *due*:
    ``last_added_at IS NULL`` or ``last_added_at + cadence_days`` has passed. Cadence is in
    days, not sessions — an ad-hoc single-recipe session is an unreliable clock. Managed in
    Settings, seeded empty. See CLAUDE.md > Checklist Screen Logic > "The usuals" and >
    Data Model > usual_items.
    """

    __tablename__ = "usual_items"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)  # normalised lowercase
    notes = Column(Text, nullable=True)
    cadence_days = Column(Integer, nullable=False)  # "buy roughly every N days"
    last_added_at = Column(DateTime, nullable=True)  # stamped when actually pushed to AnyList
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class RememberedSubstitution(Base):
    """A quick-pick library entry (Phase 3.9 M4 — was ``IngredientSubstitution`` with an
    ``is_default`` that auto-applied; that's gone). It NEVER applies a swap on its own — it
    only pre-fills / top-ranks the suggestion in a per-recipe confirm UI. Every row exists
    because the user ticked "save this swap" at capture review, the recipe editor, or after a
    planning swap. See CLAUDE.md > AI Provider Migration > Ingredient Substitution Flagging
    and > Data Model > remembered_substitutions.
    """

    __tablename__ = "remembered_substitutions"
    __table_args__ = (
        UniqueConstraint("original_name", "substitute_name", name="uq_substitution_pair"),
    )

    id = Column(Integer, primary_key=True)
    original_name = Column(Text, nullable=False)  # normalised lowercase, matches recipe_ingredients.name
    substitute_name = Column(Text, nullable=False)  # normalised lowercase (freetext; 1:many stored verbatim)
    note = Column(Text, nullable=True)  # pre-fills recipe_ingredients.substitution_note
    last_used_at = Column(DateTime, nullable=True)  # quick-pick ordering, most-recent first
    # Quantity/unit equivalence (Phase 3.9 M8 — see CLAUDE.md > AI Provider Migration >
    # Ingredient Substitution Flagging, and > Data Model > remembered_substitutions).
    # "original_qty original_unit ~= substitute_qty substitute_unit", e.g. 2 "cob" ~= 2 "can".
    # A ratio the quick-pick uses to PRE-FILL recipe_ingredients' resolved_quantity /
    # resolved_unit for whatever amount that recipe calls for; the user still confirms. All
    # four NULL = a name-only quick-pick (unchanged from M4). Never auto-applied. original_qty
    # must be > 0 when set.
    original_qty = Column(Float, nullable=True)
    original_unit = Column(Text, nullable=True)
    substitute_qty = Column(Float, nullable=True)
    substitute_unit = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

"""``product_units``, ``staples`` and ``ingredient_substitutions`` — the editable
reference catalogue managed from the Settings page."""

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


class IngredientSubstitution(Base):
    """A user-kept rule that treats one product as interchangeable with another for
    shopping purposes (e.g. "bulgarian feta" -> "regular feta"). Never pre-seeded — every
    row exists because the user made and kept a real substitution during planning. At most
    one ``is_default`` TRUE per ``original_name`` is enforced in ``services/``, not by a DB
    constraint (SQLite has no clean partial-unique-index story via the ORM here) — same
    pattern as the duplicate-name 409s in services/settings.py. See CLAUDE.md >
    Ingredient Substitution and > Data Model > ingredient_substitutions.
    """

    __tablename__ = "ingredient_substitutions"
    __table_args__ = (
        UniqueConstraint("original_name", "substitute_name", name="uq_substitution_pair"),
    )

    id = Column(Integer, primary_key=True)
    original_name = Column(Text, nullable=False)  # normalised lowercase, matches recipe_ingredients.name
    substitute_name = Column(Text, nullable=False)  # normalised lowercase
    is_default = Column(Boolean, nullable=False, default=False)  # the silently auto-applied one
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

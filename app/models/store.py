"""``stores``, ``store_sections`` and ``product_sections`` tables.

From the Shop Layout Reorganisation addendum in CLAUDE.md. A product's *section*
(e.g. "dairy") is a property of the ingredient, store-independent. A store's
*section order* (walking order) is a property of the store, product-independent.
Sorting a list for a given store is: group by section -> order groups by that
store's section order -> render. AnyList itself is never modified by this.

``product_sections`` keys off ``ingredient_name`` (text), the same normalised-name
convention already used by ``product_units.ingredient_name`` / ``recipe_ingredients.name``
— there is no separate numeric "product" entity in this schema.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base, utcnow


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    sections = relationship(
        "StoreSection",
        back_populates="store",
        cascade="all, delete-orphan",
        order_by="StoreSection.sort_order",
    )


class StoreSection(Base):
    """One row per (store, section) — this store's walking-order position for that section."""

    __tablename__ = "store_sections"
    __table_args__ = (UniqueConstraint("store_id", "section_name", name="uq_store_section"),)

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    section_name = Column(Text, nullable=False)  # matches the canonical section vocabulary
    sort_order = Column(Integer, nullable=False, default=0)  # position in this store's walk order
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    store = relationship("Store", back_populates="sections")


class ProductSection(Base):
    """Which section an ingredient belongs to. Store-independent, keyed by ingredient_name."""

    __tablename__ = "product_sections"

    id = Column(Integer, primary_key=True)
    ingredient_name = Column(Text, nullable=False, unique=True)  # matches product_units.ingredient_name
    section_name = Column(Text, nullable=False)
    source = Column(Text, nullable=False, default="user_confirmed")  # ai_suggested|user_confirmed|user_corrected
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

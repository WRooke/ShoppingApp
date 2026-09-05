"""``product_units`` and ``staples`` tables — the editable reference catalogue."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text

from app.database import Base, utcnow


class ProductUnit(Base):
    __tablename__ = "product_units"

    id = Column(Integer, primary_key=True)
    ingredient_name = Column(Text, nullable=False, unique=True)  # matches recipe_ingredients.name
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

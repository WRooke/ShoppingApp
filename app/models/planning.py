"""``planning_sessions``, ``session_recipes`` and ``session_checklist_items`` tables."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base, utcnow


class PlanningSession(Base):
    __tablename__ = "planning_sessions"

    id = Column(Integer, primary_key=True)
    label = Column(Text, nullable=True)  # e.g. "Week of 14 Jul"
    status = Column(Text, nullable=False, default="active")  # 'active' | 'pushed' | 'archived'
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    pushed_at = Column(DateTime, nullable=True)

    recipes = relationship(
        "SessionRecipe",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionRecipe.sort_order",
    )
    checklist_items = relationship(
        "SessionChecklistItem",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class SessionRecipe(Base):
    __tablename__ = "session_recipes"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey("planning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Phase 4 (Chunk 4.1): a slot can be a real recipe or a non-recipe "leftovers" marker
    # that pulls nothing into consolidation, so recipe_id is nullable and slot_type flags
    # which it is. See CLAUDE.md > Data Model > session_recipes (Phase 4 note).
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    slot_type = Column(Text, nullable=False, default="recipe")  # 'recipe' | 'leftovers'
    day_of_week = Column(Integer, nullable=True)  # 1=Monday .. 7=Sunday
    scaled_servings = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    session = relationship("PlanningSession", back_populates="recipes")


class SessionChecklistItem(Base):
    __tablename__ = "session_checklist_items"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey("planning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_name = Column(Text, nullable=False)  # consolidated, normalised
    total_quantity = Column(Float, nullable=True)
    total_unit = Column(Text, nullable=True)
    is_staple = Column(Boolean, nullable=False, default=False)
    already_on_anylist = Column(Boolean, nullable=False, default=False)
    have_it = Column(Text, nullable=False, default="unknown")  # 'yes'|'no'|'partial'|'unknown'
    add_to_list = Column(Boolean, nullable=False, default=False)
    purchase_label = Column(Text, nullable=True)
    purchase_qty = Column(Float, nullable=True)
    display_qty = Column(Text, nullable=True)  # e.g. "2 x 500g packs"
    anylist_item_id = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    session = relationship("PlanningSession", back_populates="checklist_items")

"""``planning_sessions``, ``session_recipes`` and ``session_checklist_items`` tables."""

from __future__ import annotations

import json

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
    # Read-only convenience so a slot can render "which recipe" without a second query.
    # joined so listing a session's slots doesn't N+1. NULL for a 'leftovers' slot.
    recipe = relationship("Recipe", lazy="joined", viewonly=True)


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
    # Phase 4 Chunk 4.6 — a display-only hint carrying an irreconcilable-units breakdown
    # ("100 g + 200 ml"), a "to taste" marker, or an overage note ("450 g spare"). See
    # CLAUDE.md > Scaling Logic > Rounding & unit rules.
    needs_review = Column(Boolean, nullable=False, default=False)
    note = Column(Text, nullable=True)
    # 2026-09-10 hand-testing — marks a needs_review conflict the user manually resolved
    # (services/checklist.py > resolve_item()) so a later consolidate_session() recompute
    # doesn't clobber it while the same ingredient still conflicts. Cleared once the conflict
    # is gone. See CLAUDE.md > Scaling Logic > re-running consolidation.
    review_resolved_by_user = Column(Boolean, nullable=False, default=False)
    # 2026-09-13 code review — JSON array of {"quantity": float, "unit": str|None}, one per
    # `needs_review` conflict part (e.g. [{"quantity": 100, "unit": "g"}, {"quantity": 200,
    # "unit": "ml"}]); NULL when the line isn't (or is no longer) needs_review. Replaces
    # frontend regex-parsing of `note` (checklist.js > parseNoteParts()) to build the
    # "use 100 g" quick-resolve buttons — `note` can carry extra appended text (an alias
    # conversion fragment) alongside the review breakdown, which the regex had no reliable way
    # to tell apart from the breakdown itself. See services/consolidation.py > ReviewOption
    # and CLAUDE.md > Scaling Logic > Rounding & unit rules > Irreconcilable.
    review_options_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    session = relationship("PlanningSession", back_populates="checklist_items")

    @property
    def review_options(self) -> list[dict]:
        """Parsed review_options_json, always a list (never None) — same pattern as
        Recipe.ai_pending_tasks. Read by ChecklistItemRead via from_attributes."""
        if not self.review_options_json:
            return []
        try:
            value = json.loads(self.review_options_json)
            return value if isinstance(value, list) else []
        except (ValueError, TypeError):
            return []

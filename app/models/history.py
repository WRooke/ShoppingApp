"""``shopping_history`` table — one row per push to AnyList."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from app.database import Base, utcnow


class ShoppingHistory(Base):
    __tablename__ = "shopping_history"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("planning_sessions.id"), nullable=False, index=True)
    pushed_at = Column(DateTime, nullable=False, default=utcnow)
    items_json = Column(Text, nullable=False)  # JSON snapshot of what was pushed
    anylist_response_json = Column(Text, nullable=True)  # raw AnyList response, for diagnostics

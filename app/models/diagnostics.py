"""``api_usage`` table — one row per billable Claude API call."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, Text

from app.database import Base, utcnow


class ApiUsage(Base):
    __tablename__ = "api_usage"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow)
    model = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cost_usd_cents = Column(Float, nullable=False)  # calculated at call time
    call_type = Column(Text, nullable=False)  # 'recipe_url'|'recipe_photo'|'ingredient_normalise'
    context_id = Column(Text, nullable=True)  # e.g. recipe id, for traceability

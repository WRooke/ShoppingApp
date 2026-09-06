"""``api_usage`` table — one row per billable Claude API call — plus ``api_usage_resets``,
which backs the diagnostics "reset spend tracker" button (see CLAUDE.md > Data Model and
Security > §0b). Both are genuinely append-only: nothing in the app ever updates or deletes a
row in either table. A "reset" only inserts a new ``api_usage_resets`` row; the diagnostics
running-total display then sums ``api_usage`` rows newer than the latest reset, so the full
call history stays intact for real observability even after the visible counter is cleared."""

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


class ApiUsageReset(Base):
    """One row per "reset spend tracker" click. See the module docstring — this never touches
    ApiUsage rows themselves, it just moves the point the diagnostics display sums forward
    from."""

    __tablename__ = "api_usage_resets"

    id = Column(Integer, primary_key=True)
    reset_at = Column(DateTime, nullable=False, default=utcnow)

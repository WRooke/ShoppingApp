"""``capture_queue`` — recipe-capture AI tasks deferred because both Gemini models hit
their quota (429). Retried ~hourly by a lifespan background poller. See CLAUDE.md >
Data Model > capture_queue and > AI Provider Migration (Phase 3.9 M3)."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from app.database import Base, utcnow


class CaptureQueueItem(Base):
    __tablename__ = "capture_queue"

    id = Column(Integer, primary_key=True)
    task = Column(Text, nullable=False)  # extract_url | extract_photo | flag_substitutions | suggest_sections
    payload_json = Column(Text, nullable=False)  # {url|text} or {image_path}; + {recipe_id} for enrichment
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    queued_at = Column(DateTime, nullable=False, default=utcnow)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

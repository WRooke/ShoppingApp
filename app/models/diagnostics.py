"""``ai_call_log`` — one append-only row per *attempted* Gemini call (Phase 3.9 M5;
replaced ``api_usage`` + ``api_usage_resets``). Gemini's free tier has no per-call dollar
cost, so there is no cost column and no "reset spend tracker" — the diagnostics page counts
today's rows per model (quota indicator) and lists the most recent (attempt log). See
CLAUDE.md > Data Model > ai_call_log."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Text

from app.database import Base, utcnow


class AiCallLog(Base):
    __tablename__ = "ai_call_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow)
    task = Column(Text, nullable=False)  # 'extract' | 'flag_substitutions' | 'suggest_sections'
    model = Column(Text, nullable=False)  # e.g. 'gemini-flash-latest' | 'gemini-flash-lite-latest'
    outcome = Column(Text, nullable=False)  # 'success' | 'quota' | 'error'
    input_tokens = Column(Integer, nullable=True)  # unknown on a pre-response failure
    output_tokens = Column(Integer, nullable=True)
    error_detail = Column(Text, nullable=True)
    context_id = Column(Text, nullable=True)  # e.g. recipe id / capture_queue id

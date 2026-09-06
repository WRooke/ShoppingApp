"""AI call logging + quota observability (Phase 3.9 M5 — replaced ``api_usage.py``).

Gemini's free tier has no per-call dollar cost, so there is no cost math and no "reset spend
tracker". ``ai_extraction.py`` calls ``log_ai_call()`` for every attempted Gemini call
(success, quota-exhausted, or error). The diagnostics page counts today's rows per model
(quota indicator) and lists the most recent (attempt log). See CLAUDE.md > Data Model >
ai_call_log and > AI Provider Migration > Diagnostics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.diagnostics import AiCallLog

logger = logging.getLogger(__name__)

# Map the AI-call `call_type` (recipe_url / recipe_photo / flag_substitutions /
# suggest_sections) to the ai_call_log.task vocabulary.
_TASK = {
    "recipe_url": "extract",
    "recipe_photo": "extract",
    "flag_substitutions": "flag_substitutions",
    "suggest_sections": "suggest_sections",
}


def task_for(call_type: str) -> str:
    return _TASK.get(call_type, call_type)


def log_ai_call(
    db: Session,
    *,
    call_type: str,
    model: str,
    outcome: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_detail: str | None = None,
    context_id: str | None = None,
) -> AiCallLog:
    """One append-only row. `outcome` is 'success' | 'quota' | 'error'."""
    row = AiCallLog(
        task=task_for(call_type),
        model=model,
        outcome=outcome,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_detail=(error_detail[:2000] if error_detail else None),
        context_id=context_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "ai_call_log: task=%s model=%s outcome=%s tokens=%s/%s",
        row.task,
        model,
        outcome,
        input_tokens,
        output_tokens,
    )
    return row


def _local_midnight_utc() -> datetime:
    """Start of today in the machine's local time, as an aware UTC datetime (ai_call_log
    timestamps are UTC — see app.database.utcnow)."""
    now_local = datetime.now().astimezone()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def today_counts_by_model(db: Session) -> dict[str, int]:
    """{model: attempt count} since local midnight — the diagnostics quota indicator.
    Best-effort: Gemini's free-tier caps aren't reliably documented, so this is an observed
    count, not 'X of Y'."""
    rows = (
        db.query(AiCallLog.model, func.count(AiCallLog.id))
        .filter(AiCallLog.timestamp >= _local_midnight_utc())
        .group_by(AiCallLog.model)
        .all()
    )
    return {model: int(count) for model, count in rows}


def recent_calls(db: Session, *, limit: int = 20) -> list[AiCallLog]:
    return (
        db.query(AiCallLog)
        .order_by(AiCallLog.timestamp.desc(), AiCallLog.id.desc())
        .limit(limit)
        .all()
    )


def last_success_at(db: Session):
    return (
        db.query(func.max(AiCallLog.timestamp))
        .filter(AiCallLog.outcome == "success")
        .scalar()
    )

"""AI call logging + quota observability (Phase 3.9 M5 — replaced ``api_usage.py``).

Gemini's free tier has no per-call dollar cost, so there is no cost math and no "reset spend
tracker". ``ai_extraction.py`` calls ``log_ai_call()`` for every attempted Gemini call
(success, quota-exhausted, or error). The diagnostics page counts today's rows per model
(quota indicator) and lists the most recent (attempt log). See docs/data-model.md > Data Model >
ai_call_log and > AI Provider Migration > Diagnostics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.diagnostics import AiCallLog

logger = logging.getLogger(__name__)

# Map the AI-call `call_type` (recipe_url / recipe_photo / suggest_sections / classify_units)
# to the ai_call_log.task vocabulary.
_TASK = {
    "recipe_url": "extract",
    "recipe_photo": "extract",
    # "flag_substitutions" removed 2026-09-30 along with the AI substitution-flagging call
    # itself — kept out of this map deliberately, but NOT removed from historical
    # ai_call_log/capture_queue rows (the never-lose-production-data rule: no destructive change to existing data). Old
    # rows with task="flag_substitutions" stay exactly as logged; task_for() below only
    # affects new calls, and nothing calls it with this call_type any more.
    "suggest_sections": "suggest_sections",
    "classify_units": "classify_units",  # admin reduction (2026-09-12), unrelated to capture
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


def mark_unparseable(db: Session, *, call_type: str, context_id: str | None, reason: str) -> None:
    """Flip the most recent ``success`` row for this call to ``error``.

    The success row is written as soon as Gemini answers, i.e. before the caller has tried to parse
    the reply — so a reply that turns out unusable used to leave a green "success" in Diagnostics
    (and in ``last_success``) for a call that produced nothing (2026-10-07 logging audit). Never
    raises: this runs inside an error path and must not mask the real failure."""
    try:
        row = (
            db.query(AiCallLog)
            .filter(
                AiCallLog.task == task_for(call_type),
                AiCallLog.context_id == context_id,
                AiCallLog.outcome == "success",
            )
            .order_by(AiCallLog.id.desc())
            .first()
        )
        if row is not None:
            row.outcome = "error"
            row.error_detail = reason[:2000]
            db.commit()
    except Exception:  # noqa: BLE001
        logger.error("ai_call_log: could not mark call %s/%s unparseable", call_type, context_id, exc_info=True)
        db.rollback()


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

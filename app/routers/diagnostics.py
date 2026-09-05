"""Diagnostics API — backs the /diagnostics page.

Phase 1 provides:
  * GET /api/v1/diagnostics/logs           live log tail (ring buffer)
  * GET /api/v1/diagnostics/recent-errors  last 10 ERROR+ entries
  * GET /api/v1/diagnostics/status         component status panel + spend

Claude and AnyList indicators are stubs until Phases 3 and 5 respectively.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.log_config import get_log_entries
from app.models.diagnostics import ApiUsage
from app.services.api_usage import get_spend_cap_usd_cents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


@router.get("/logs")
def logs(
    limit: int = Query(200, ge=1, le=1000),
    level: str | None = Query(None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    offset: int = Query(0, ge=0),
) -> dict:
    entries = get_log_entries(limit=limit + offset, level=level)
    if offset:
        entries = entries[offset:]
    return {"ok": True, "data": {"entries": entries[:limit], "count": len(entries[:limit])}}


@router.get("/recent-errors")
def recent_errors() -> dict:
    entries = get_log_entries(limit=1000, level="ERROR")[:10]
    return {"ok": True, "data": {"entries": entries}}


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    # --- database -------------------------------------------------------
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        logger.error("Diagnostics: database probe failed", exc_info=True)

    database = {
        "state": "green" if db_ok else "red",
        "message": "Connected" if db_ok else "Connection failed",
    }

    # --- Claude API -----------------------------------------------------
    # Spend-cap fields are always populated (a highest-priority standing rule — see CLAUDE.md
    # > Security > API Spend Cap — must be visible on diagnostics regardless of what phase the
    # rest of the Claude integration has reached).
    spend_cap_usd_cents = get_spend_cap_usd_cents()
    claude = {
        "state": "grey",
        "message": "Not wired up yet - Phase 3",
        "last_success": None,
        "estimated_spend_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "spend_cap_aud_cents": settings.max_api_spend_aud_cents,
        "spend_cap_usd_cents": round(spend_cap_usd_cents, 4),
        "remaining_usd_cents": round(spend_cap_usd_cents, 4),
        "spend_cap_reached": False,
    }
    try:
        spend_cents, in_tok, out_tok, last_ts = db.query(
            func.coalesce(func.sum(ApiUsage.cost_usd_cents), 0.0),
            func.coalesce(func.sum(ApiUsage.input_tokens), 0),
            func.coalesce(func.sum(ApiUsage.output_tokens), 0),
            func.max(ApiUsage.timestamp),
        ).one()
        spend_cents = spend_cents or 0.0
        claude["estimated_spend_usd"] = round(spend_cents / 100.0, 4)
        claude["total_input_tokens"] = int(in_tok or 0)
        claude["total_output_tokens"] = int(out_tok or 0)
        claude["remaining_usd_cents"] = round(max(spend_cap_usd_cents - spend_cents, 0.0), 4)
        claude["spend_cap_reached"] = spend_cents >= spend_cap_usd_cents
        if claude["spend_cap_reached"]:
            claude["state"] = "red"
            claude["message"] = "Spend cap reached — further Claude calls are refused"
        elif last_ts is not None:
            claude["last_success"] = str(last_ts)
            claude["state"] = "green"
            claude["message"] = "OK"
        elif settings.anthropic_configured:
            claude["state"] = "amber"
            claude["message"] = "Key configured, no calls yet"
    except Exception:  # noqa: BLE001
        logger.error("Diagnostics: api_usage aggregate query failed", exc_info=True)

    # --- AnyList (stub until Phase 5) --------------------------------
    anylist = {
        "state": "grey" if not settings.anylist_configured else "amber",
        "message": (
            "Not wired up yet - Phase 5"
            if not settings.anylist_configured
            else "Credentials configured, connector not built yet - Phase 5"
        ),
        "last_success": None,
    }

    return {
        "ok": True,
        "data": {
            "database": database,
            "claude_api": claude,
            "anylist": anylist,
        },
    }

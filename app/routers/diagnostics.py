"""Diagnostics API — backs the /diagnostics page.

Provides:
  * GET  /api/v1/diagnostics/logs           live log tail (ring buffer)
  * GET  /api/v1/diagnostics/recent-errors  last 10 ERROR+ entries
  * GET  /api/v1/diagnostics/status         component status panel + spend tracker
  * POST /api/v1/diagnostics/reset-spend    reset the displayed spend tracker (CLAUDE.md >
                                             Security §0b) — never touches the underlying
                                             api_usage log, see api_usage.reset_api_usage_display()

AnyList indicator is a stub until Phase 5.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.log_config import get_log_entries
from app.services.api_usage import get_display_totals, reset_api_usage_display

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

    # --- AI extraction (Gemini) --------------------------------------------
    # Enable-switch and fake-mode fields are always populated — a highest-priority standing
    # rule (CLAUDE.md > Security §0c). Spend/token totals are observability only (§0b).
    # NOTE: Phase 3.9 M5 replaces this whole block (quota indicator + attempt log, no USD);
    # M1 just carries it over with the renamed settings attributes.
    claude = {
        "state": "grey",
        "message": "Gemini API key not configured",
        "last_success": None,
        "estimated_spend_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "reset_at": None,
        "api_enabled": settings.ai_extraction_enabled,
        "fake_mode": settings.ai_extraction_fake_mode,
    }
    try:
        spend_cents, in_tok, out_tok, last_ts, reset_at = get_display_totals(db)
        claude["estimated_spend_usd"] = round(spend_cents / 100.0, 4)
        claude["total_input_tokens"] = in_tok
        claude["total_output_tokens"] = out_tok
        claude["reset_at"] = str(reset_at) if reset_at is not None else None

        if claude["fake_mode"]:
            claude["state"] = "amber"
            claude["message"] = "FAKE MODE — extraction returns canned fixtures, no real Gemini calls are made"
        elif not claude["api_enabled"]:
            claude["state"] = "grey"
            claude["message"] = "Disabled (AI_EXTRACTION_ENABLED=false in .env) — enable explicitly to use recipe capture"
        elif last_ts is not None:
            claude["last_success"] = str(last_ts)
            claude["state"] = "green"
            claude["message"] = "OK"
        elif settings.gemini_configured:
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


@router.post("/reset-spend")
def reset_spend(db: Session = Depends(get_db)) -> dict:
    """Resets the diagnostics-page spend/token tracker (CLAUDE.md > Diagnostics & Logging >
    "Reset button (with confirmation)"; Security §0b). Purely a display reset — inserts a row
    into `api_usage_resets` and never touches an `api_usage` row, so the full call history
    stays intact. The frontend confirms before calling this (see static/js/diagnostics.js)."""
    marker = reset_api_usage_display(db)
    logger.info("Diagnostics: spend tracker reset via API at %s", marker.reset_at)
    return {"ok": True, "data": {"reset_at": str(marker.reset_at)}}

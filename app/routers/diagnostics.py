"""Diagnostics API — backs the /diagnostics page.

Provides:
  * GET  /api/v1/diagnostics/logs           live log tail (ring buffer)
  * GET  /api/v1/diagnostics/recent-errors  last 10 ERROR+ entries
  * GET  /api/v1/diagnostics/status         component status panel + AI quota / attempt log

AnyList indicator is a stub until Phase 5. Phase 3.9 M5 replaced the USD "spend tracker" +
its reset button with a Gemini daily-quota indicator + recent-attempt log (free tier, no
per-call cost).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.log_config import get_log_entries
from app.services import ai_call_log

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

    # --- AI extraction (Gemini) — Phase 3.9 M5 --------------------------------
    # Enable-switch / fake-mode fields are always populated (§0c). Quota = an observed
    # request count per model since local midnight; no dollar cost on Gemini's free tier.
    ai = {
        "state": "grey",
        "message": "Gemini API key not configured",
        "api_enabled": settings.ai_extraction_enabled,
        "fake_mode": settings.ai_extraction_fake_mode,
        "last_success": None,
        "today_by_model": {},
        "recent_calls": [],
        "dashboard_url": "https://aistudio.google.com/app/apikey",
    }
    try:
        ai["today_by_model"] = ai_call_log.today_counts_by_model(db)
        last_ok = ai_call_log.last_success_at(db)
        ai["last_success"] = str(last_ok) if last_ok is not None else None
        ai["recent_calls"] = [
            {
                "time": r.timestamp.isoformat(timespec="seconds"),
                "task": r.task,
                "model": r.model,
                "outcome": r.outcome,
                "error_detail": r.error_detail,
            }
            for r in ai_call_log.recent_calls(db, limit=15)
        ]

        if ai["fake_mode"]:
            ai["state"] = "amber"
            ai["message"] = "FAKE MODE — extraction returns canned fixtures, no real Gemini calls are made"
        elif not ai["api_enabled"]:
            ai["state"] = "grey"
            ai["message"] = "Disabled (AI_EXTRACTION_ENABLED=false in .env) — enable explicitly to use recipe capture"
        elif last_ok is not None:
            ai["state"] = "green"
            ai["message"] = "OK"
        elif settings.gemini_configured:
            ai["state"] = "amber"
            ai["message"] = "Key configured, no calls yet"
    except Exception:  # noqa: BLE001
        logger.error("Diagnostics: ai_call_log query failed", exc_info=True)

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
            "ai_extraction": ai,
            "anylist": anylist,
        },
    }

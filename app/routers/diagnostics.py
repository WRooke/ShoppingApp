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

import json as _json
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.log_config import get_log_entries
from app.models.history import ShoppingHistory
from app.models.queue import CaptureQueueItem
from app.services import ai_call_log
from app.services import anylist_client

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
    """The component status panel: a `database`, `ai_extraction` (Gemini) and `anylist`
    block, each with a green/amber/red `state` + `message`. The AI block also carries the
    §0c enable/fake-mode flags, the daily quota indicator (`today_by_model`), the recent
    capture-attempt log, and the retry-queue summary. Every sub-query is wrapped so one
    failing block still returns the others."""
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
        "queue": {"depth": 0, "items": []},
        "dashboard_url": "https://aistudio.google.com/app/apikey",
    }
    try:
        queued = (
            db.query(CaptureQueueItem)
            .order_by(CaptureQueueItem.queued_at.asc())
            .limit(20)
            .all()
        )
        ai["queue"] = {
            "depth": db.query(CaptureQueueItem).count(),
            "items": [
                {
                    "task": q.task,
                    "recipe_id": q.recipe_id,
                    "queued_at": q.queued_at.isoformat(timespec="seconds"),
                    "attempt_count": q.attempt_count,
                    "last_error": q.last_error,
                }
                for q in queued
            ],
        }
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

    # --- AnyList (Phase 5) -----------------------------------------
    # No live round-trip here (it would re-login on every auto-poll). Reports config state +
    # the last in-process success + the most recent push; POST /diagnostics/anylist-check
    # does an explicit auth round-trip on demand.
    anylist = {
        "enabled": settings.anylist_enabled,
        "fake_mode": settings.anylist_fake_mode,
        "target_list": settings.anylist_target_list_name,
        "credentials_configured": settings.anylist_configured,
        "secret_source": settings.anylist_secret_source,
        "last_success": None,
        "last_push": None,
        "state": "grey",
        "message": "",
    }
    try:
        anylist_last_ok = anylist_client.last_success_at()
        anylist["last_success"] = str(anylist_last_ok) if anylist_last_ok else None
        last_push_row = (
            db.query(ShoppingHistory).order_by(ShoppingHistory.pushed_at.desc()).first()
        )
        if last_push_row is not None:
            try:
                resp = _json.loads(last_push_row.anylist_response_json or "{}")
            except ValueError:
                resp = {}
            anylist["last_push"] = {
                "session_id": last_push_row.session_id,
                "pushed_at": str(last_push_row.pushed_at),
                "confirmed": not resp.get("discrepancies"),
            }
        if not settings.anylist_enabled and not settings.anylist_fake_mode:
            anylist["state"], anylist["message"] = "grey", "AnyList sync is switched off (ANYLIST_ENABLED=false)"
        elif settings.anylist_fake_mode:
            anylist["state"], anylist["message"] = "amber", "FAKE MODE — in-memory list, no real AnyList calls"
        elif not settings.anylist_configured:
            anylist["state"], anylist["message"] = "red", "Enabled but no credentials (see Security §2)"
        elif anylist["last_push"] and not anylist["last_push"]["confirmed"]:
            anylist["state"], anylist["message"] = "red", "Last push was not fully confirmed — check AnyList"
        elif anylist_last_ok:
            anylist["state"], anylist["message"] = "green", f"Last success {anylist_last_ok}"
        else:
            anylist["state"], anylist["message"] = "amber", "Enabled and configured; no call made yet"
    except Exception:  # noqa: BLE001
        logger.error("Diagnostics: anylist status build failed", exc_info=True)
        anylist["state"], anylist["message"] = "red", "status query failed"

    return {
        "ok": True,
        "data": {
            "database": database,
            "ai_extraction": ai,
            "anylist": anylist,
        },
    }


@router.post("/anylist-check")
def anylist_check() -> dict:
    """On-demand AnyList auth round-trip (fake or real) — the /diagnostics page's
    "Check AnyList now" button. Never raises; returns a timestamped status."""
    status = anylist_client.check_auth()
    return {
        "ok": True,
        "data": {"ok": status.ok, "detail": status.detail, "checked_at": str(status.checked_at)},
    }

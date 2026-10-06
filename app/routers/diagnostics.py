"""Diagnostics API — backs the /diagnostics page.

Provides:
  * GET  /api/v1/diagnostics/logs           live log tail (ring buffer)
  * GET  /api/v1/diagnostics/recent-errors  all ERROR+ entries currently in the ring buffer
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
from app.log_config import RING_BUFFER_MAXLEN, get_log_entries
from app.models.history import ShoppingHistory
from app.models.queue import CaptureQueueItem
from app.services import ai_call_log
from app.services import anylist_client
from app.services import capture_queue
from app.services.version import get_build_info

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
    # Returns every ERROR+ entry currently held in the ring buffer, not a fixed slice
    # (diagnostics chunk 7.7, 5a — a truncated "last 10" was hiding real errors on a busy
    # day). limit=RING_BUFFER_MAXLEN so nothing the buffer holds is ever cut off here; the
    # buffer's own maxlen is what actually bounds how far back this can reach.
    entries = get_log_entries(limit=RING_BUFFER_MAXLEN, level="ERROR")
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
            # 2026-09-13 code review — run_once() never drops/caps a retry (never silently
            # lose a household's capture), so a permanently-broken item just keeps
            # re-attempting hourly forever with nothing to distinguish it from one still
            # working through transient quota exhaustion. Flag it once attempt_count crosses
            # STALLED_AFTER_ATTEMPTS instead — surfaced here, not acted on.
            "stalled_count": sum(
                1 for q in queued if q.attempt_count >= capture_queue.STALLED_AFTER_ATTEMPTS
            ),
            "items": [
                {
                    "task": q.task,
                    "recipe_id": q.recipe_id,
                    "queued_at": q.queued_at.isoformat(timespec="seconds"),
                    "attempt_count": q.attempt_count,
                    "last_error": q.last_error,
                    "stalled": q.attempt_count >= capture_queue.STALLED_AFTER_ATTEMPTS,
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
            anylist["last_push"] = _summarise_push(last_push_row, resp)
            recent = (
                db.query(ShoppingHistory).order_by(ShoppingHistory.pushed_at.desc()).limit(5).all()
            )
            anylist["recent_pushes"] = [_summarise_push(r) for r in recent]
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

    build = get_build_info()
    return {
        "ok": True,
        "data": {
            "database": database,
            "ai_extraction": ai,
            "anylist": anylist,
            # Which code is running, since when — answers "is the NUC on what I just deployed?"
            # (docs/deployment-and-operations.md). Same values as /health.
            "build": {
                "build_id": build.build_id, "version": build.label, "version_source": build.label_source,
                "boot_id": build.boot_id, "started_at": build.started_at,
            },
        },
    }


def _summarise_push(row: ShoppingHistory, resp: dict | None = None) -> dict:
    """One shopping_history row as the Diagnostics page shows it: when, which push (``push_id``
    ties it to the log lines), whether every line was confirmed, counts per outcome, and — the
    point of 6.7 — the full per-item result, so "why didn't X arrive?" is answerable from here
    without reading logs (docs/anylist-push.md > Runbook). Older rows (pushed before per-item
    results existed) simply have no ``items``."""
    if resp is None:
        try:
            resp = _json.loads(row.anylist_response_json or "{}")
        except ValueError:
            resp = {}
    items = resp.get("items") or []
    counts: dict[str, int] = {}
    for it in items:
        counts[it.get("outcome", "?")] = counts.get(it.get("outcome", "?"), 0) + 1
    return {
        "history_id": row.id,
        "session_id": row.session_id,
        "pushed_at": str(row.pushed_at),
        "push_id": resp.get("push_id"),
        "confirmed": not resp.get("discrepancies"),
        "counts": counts,
        "discrepancies": resp.get("discrepancies") or [],
        "items": items,
        "timings": resp.get("timings") or {},
        "retried": resp.get("retried") or [],
    }


@router.get("/pushes")
def recent_pushes(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    """The most recent AnyList pushes, newest first, each with its per-item results."""
    rows = db.query(ShoppingHistory).order_by(ShoppingHistory.pushed_at.desc()).limit(limit).all()
    return {"ok": True, "data": {"pushes": [_summarise_push(r) for r in rows]}}


@router.post("/anylist-check")
def anylist_check() -> dict:
    """On-demand AnyList auth round-trip (fake or real) — the /diagnostics page's
    "Check AnyList now" button. Never raises; returns a timestamped status."""
    status = anylist_client.check_auth()
    return {
        "ok": True,
        "data": {"ok": status.ok, "detail": status.detail, "checked_at": str(status.checked_at)},
    }

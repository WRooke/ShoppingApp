"""``POST /api/v1/client-log`` — the browser reports its own errors (see
app/services/client_log.py for why, and for the untrusted-input handling)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.client_log import ClientLogReport
from app.services import client_log as client_log_service

router = APIRouter(prefix="/api/v1", tags=["client-log"])


@router.post("/client-log")
def client_log(report: ClientLogReport, request: Request) -> dict:
    """Always answers ok, even when the report was dropped by the rate limit — the page must never
    retry or show anything because its error report was refused."""
    client_id = request.client.host if request.client else "unknown"
    recorded = client_log_service.record_client_error(report, client_id=client_id)
    return {"ok": True, "data": {"recorded": recorded}}

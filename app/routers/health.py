"""Health check endpoint — ``GET /api/v1/health``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db_connected = False
    db_detail = None
    try:
        db.execute(text("SELECT 1"))
        db_connected = True
    except Exception as exc:  # noqa: BLE001
        db_detail = str(exc)
        logger.error("Health check: database probe failed", exc_info=True)

    return {
        "ok": True,
        "data": {
            "status": "ok" if db_connected else "degraded",
            "database": {
                "connected": db_connected,
                "path": settings.database_path,
                "detail": db_detail,
            },
            "config": settings.summary,
        },
    }

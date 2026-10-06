"""Health check endpoint — ``GET /api/v1/health``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.version import get_build_info

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    # Never cached: the update banner polls this to learn the server was restarted on new code, so
    # a cached answer would hide exactly the change it exists to report.
    response.headers["Cache-Control"] = "no-store"
    build = get_build_info()
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
            # Client auto-update banner (docs/ui-ux.md) compares `build_id` with the build id the
            # page was served with (<meta name="app-build">) — see static/js/update-banner.js and
            # app/services/version.py. `version` is the human label only (git describe) and is
            # never compared; `boot_id`/`started_at` tell a restart from a no-op on Diagnostics.
            "build_id": build.build_id,
            "version": build.label,
            "version_source": build.label_source,
            "boot_id": build.boot_id,
            "started_at": build.started_at,
            "database": {
                "connected": db_connected,
                "path": settings.database_path,
                "detail": db_detail,
            },
            "config": settings.summary,
        },
    }

"""Settings API — staples and product_units editing. Implemented in Phase 2."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

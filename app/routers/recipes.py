"""Recipe library API. Implemented in Phase 2 (see CLAUDE.md > Build Phases)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/recipes", tags=["recipes"])

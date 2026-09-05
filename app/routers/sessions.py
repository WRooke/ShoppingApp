"""Planning session API. Implemented in Phase 4 (see CLAUDE.md > Build Phases)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

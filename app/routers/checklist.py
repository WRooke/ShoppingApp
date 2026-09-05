"""Checklist screen API. Implemented in Phase 5 (see CLAUDE.md > Build Phases)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/checklist", tags=["checklist"])

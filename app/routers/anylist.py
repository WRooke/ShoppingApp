"""AnyList integration API. Implemented in Phase 5.

NOTE for Phase 5: the native-Python vs Node-microservice decision must be
flagged to Will before implementation (see CLAUDE.md > Tech Stack > AnyList).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/anylist", tags=["anylist"])

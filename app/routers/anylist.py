"""AnyList router — intentionally empty.

Phase 5's AnyList work is exposed through the checklist flow
(``routers/checklist.py`` → ``services/checklist.py`` → ``services/anylist_client.py``) and
the diagnostics ``anylist`` block / ``POST /diagnostics/anylist-check``, not through
dedicated ``/api/v1/anylist/*`` endpoints. The native-vs-Node decision was settled by the
Phase 1.5 spike (Python-native — see CLAUDE.md > Tech Stack > AnyList integration). This
prefix is kept registered in case a direct AnyList admin endpoint is wanted later.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/anylist", tags=["anylist"])

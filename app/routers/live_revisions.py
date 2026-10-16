"""Router-layer dependency that feeds the live checklist's revision counter (Chunk 6.7, polish
batch 3, item C). Lives in ``routers/`` because it needs FastAPI's ``Request``; the counter itself
is ``services/checklist_revisions.py``."""

from __future__ import annotations

from typing import Iterator

from fastapi import Request

from app.services import checklist_revisions


def bump_on_write(request: Request) -> Iterator[None]:
    """After any non-GET request on the checklist or sessions routers has run, bump the plan
    named by the URL's ``{session_id}``; a checklist write with no plan in its URL (the usuals'
    "skip") bumps every plan. Bumping after a failed request is harmless - phones just do one
    redundant read.

    Done here, once, instead of in every endpoint, so a newly added mutating endpoint cannot be
    forgotten (tests/routers/test_checklist_live.py pins this)."""
    yield
    if request.method == "GET":
        return
    sid = request.path_params.get("session_id")
    if sid is not None:
        checklist_revisions.bump(int(sid))
    elif request.url.path.startswith("/api/v1/checklist/"):
        checklist_revisions.bump_all()

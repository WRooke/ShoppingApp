"""In-memory "something changed" counter behind the live checklist (Chunk 6.7, polish batch 3,
item C — docs/checklist-and-shopping.md > Live updates between phones).

Each plan has a revision number that goes up whenever anything that shows on its checklist is
changed by a person (a Have it / Need it tap, a panel save, a merge, a recipe added, a push ...).
A phone shows the revision it last saw and long-polls ``GET /checklist/{id}/changes``; the server
answers as soon as the number differs, so a second phone sees the change in under a second
without anyone re-reading AnyList or re-running consolidation.

**Single-worker assumption.** This is process memory. It is only correct because the app runs
as ONE uvicorn process (``app.main`` -> ``uvicorn.run`` with no ``workers``; the same assumption
``progress_tracker`` documents). A restart changes ``EPOCH``, which makes every phone treat its
last-seen number as changed and reload once - so losing the counters on restart is harmless.

Not bumped by plain consolidation inside a load: a load must never look like an edit, or two
phones refreshing would keep waking each other.
"""

from __future__ import annotations

import threading
import time

EPOCH = f"{int(time.time() * 1000):x}"  # changes on every server start

_lock = threading.Lock()
_revs: dict[int, int] = {}
_global_rev = 0  # edits that are not tied to one plan (the usuals), seen by every checklist


def bump(session_id: int) -> None:
    with _lock:
        _revs[session_id] = _revs.get(session_id, 0) + 1


def bump_all() -> None:
    global _global_rev
    with _lock:
        _global_rev += 1


def current(session_id: int) -> tuple[str, int]:
    """(epoch, revision) for a plan. The revision only ever goes up within one epoch."""
    with _lock:
        return EPOCH, _revs.get(session_id, 0) + _global_rev


def is_unchanged(session_id: int, epoch: str | None, rev: int | None) -> bool:
    return (epoch, rev) == current(session_id)

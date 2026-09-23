"""In-process progress tracking for long-running, single-HTTP-request operations that the
frontend wants to show real step-by-step feedback for — recipe capture (3 sequential Gemini
calls) and the AnyList push (one HTTP request per item). See CLAUDE.md > UI/UX > Real
progress indicators.

Both operations are one blocking request/response from the frontend's point of view, with no
existing job/status infrastructure in this app (no websockets, no task queue) — this module
is deliberately the smallest thing that closes that gap: a plain in-memory dict keyed by a
client-generated token, written to by the long-running call itself as it moves through its
own stages, and read by a cheap polling GET endpoint the frontend hits every ~500ms while the
main request is in flight.

Safe as in-memory (not a DB table): this app runs uvicorn single-process (no `--workers` flag
anywhere in start.bat/scripts/), so there is exactly one process ever writing or reading this
dict — no cross-process coordination is needed. Entries are swept lazily on write rather than
via a background thread, since this is a UI nicety, not durable state: a server restart
mid-operation simply loses the in-flight progress display, and the underlying capture/push
operation is completely unaffected either way (it isn't reading this dict at all, only
writing to it).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

_LOCK = threading.Lock()
_TTL_SECONDS = 5 * 60  # long enough to cover the slowest realistic capture/push, no more


class ProgressTokenNotFoundError(Exception):
    """Raised by the polling routers when a token is unknown — never started, already expired,
    or a typo. Translated centrally in app/main.py to a 404, same pattern as every other
    NotFound error in this app."""

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__(f"Progress token {token!r} not found")


@dataclass
class StepState:
    name: str
    status: str = "pending"  # 'pending' | 'active' | 'done' | 'failed'
    detail: str | None = None


@dataclass
class _Entry:
    steps: list[StepState]
    updated_at: float = field(default_factory=time.monotonic)


_progress: dict[str, _Entry] = {}


def _sweep_expired() -> None:
    """Caller must hold _LOCK. Drops entries older than _TTL_SECONDS — cheap enough to run on
    every write rather than needing a background thread for a dict that only ever holds a
    handful of entries (one household, a few concurrent captures/pushes at most)."""
    cutoff = time.monotonic() - _TTL_SECONDS
    stale = [token for token, entry in _progress.items() if entry.updated_at < cutoff]
    for token in stale:
        del _progress[token]


def start(token: str, step_names: list[str]) -> None:
    """Register a new tracked operation, all steps 'pending'. Called once at the top of the
    long-running function, before its first real step begins. A falsy/empty token is a no-op
    (the frontend didn't opt into progress tracking for this call) — every step_/finish
    function below is likewise a no-op for an untracked token, so callers never need to
    branch on whether a token was actually supplied."""
    if not token:
        return
    with _LOCK:
        _sweep_expired()
        _progress[token] = _Entry(steps=[StepState(name=n) for n in step_names])


def step_active(token: str, step_name: str) -> None:
    """Mark one step 'active' — called immediately before that step's real work starts."""
    if not token:
        return
    with _LOCK:
        entry = _progress.get(token)
        if not entry:
            return
        for s in entry.steps:
            if s.name == step_name:
                s.status = "active"
        entry.updated_at = time.monotonic()


def step_done(token: str, step_name: str) -> None:
    """Mark one step 'done' — called immediately after that step's real work succeeds."""
    if not token:
        return
    with _LOCK:
        entry = _progress.get(token)
        if not entry:
            return
        for s in entry.steps:
            if s.name == step_name:
                s.status = "done"
        entry.updated_at = time.monotonic()


def step_failed(token: str, step_name: str, detail: str | None = None) -> None:
    """Mark one step 'failed' — called when that step's real work raises. Does not mark any
    other step; a caller that keeps going after a swallowed failure (e.g. capture's
    enrichment calls) is responsible for its own subsequent step_active/step_done calls."""
    if not token:
        return
    with _LOCK:
        entry = _progress.get(token)
        if not entry:
            return
        for s in entry.steps:
            if s.name == step_name:
                s.status = "failed"
                s.detail = detail
        entry.updated_at = time.monotonic()


def get(token: str) -> list[dict] | None:
    """The current step list for a token, or None if the token is unknown (never started, or
    already expired) — the router translates None to 404."""
    if not token:
        return None
    with _LOCK:
        entry = _progress.get(token)
        if not entry:
            return None
        return [{"name": s.name, "status": s.status, "detail": s.detail} for s in entry.steps]

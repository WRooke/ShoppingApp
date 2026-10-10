"""Browser-side errors -> the server log (2026-10-07 logging audit).

Until now a JavaScript exception, a failed ``fetch`` or an unhandled promise rejection in the
phone's browser left no trace anywhere the maintainer could see: Diagnostics and ``app.log`` only
knew what reached the server. The page reports them here (static/js/error-report.js) and they are
written to the normal log under the ``app.client`` logger, so they appear in Recent errors with
everything else.

The endpoint is unauthenticated (LAN-only like the whole app — CLAUDE.md > Security §1), so the
input is treated as hostile: every field is length-bounded, line breaks are neutralised so a
report cannot forge log lines, query strings/fragments are stripped from the page URL, and a
per-client rate limit stops a looping page from flooding the log.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from urllib.parse import urlsplit, urlunsplit

from app.schemas.client_log import ClientLogReport

logger = logging.getLogger("app.client")

MAX_MESSAGE_CHARS = 500
MAX_STACK_CHARS = 4000
RATE_LIMIT_PER_MINUTE = 20
_WINDOW_SECONDS = 60.0
_MAX_TRACKED_CLIENTS = 100

# kind -> level. A failed fetch is routine while the server restarts for an update, so "api" is a
# WARNING; a script error / unhandled rejection / view crash is a real defect, so ERROR.
_KIND_LEVELS = {
    "error": logging.ERROR,
    "unhandledrejection": logging.ERROR,
    "route": logging.ERROR,
    "api": logging.WARNING,
    "other": logging.WARNING,
}

_recent: dict[str, deque[float]] = {}


def _one_line(text: str | None, limit: int) -> str:
    """Bound the length and remove anything that could start a fake log line."""
    return (text or "").replace("\r", " ").replace("\n", " ")[:limit]


def _page(url: str | None) -> str:
    """Host-less path + hash route only: query strings can carry tokens and add nothing here."""
    if not url:
        return "?"
    parts = urlsplit(url)
    return urlunsplit(("", "", parts.path, "", parts.fragment))[:200] or "?"


def _allowed(client_id: str, now: float) -> bool:
    window = _recent.get(client_id)
    if window is None:
        if len(_recent) >= _MAX_TRACKED_CLIENTS:
            _recent.pop(next(iter(_recent)))  # oldest-inserted; this is a flood guard, not accounting
        window = _recent.setdefault(client_id, deque())
    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        return False
    window.append(now)
    return True


def record_client_error(report: ClientLogReport, *, client_id: str, now: float | None = None) -> bool:
    """Log ``report``. Returns False (and logs nothing) when this client is over its rate limit."""
    now = time.monotonic() if now is None else now
    if not _allowed(client_id, now):
        return False
    kind = report.kind if report.kind in _KIND_LEVELS else "other"
    stack = _one_line(report.stack, MAX_STACK_CHARS)
    logger.log(
        _KIND_LEVELS[kind],
        "Browser %s on %s (build %s): %s%s",
        kind,
        _page(report.url),
        _one_line(report.build, 40) or "?",
        _one_line(report.message, MAX_MESSAGE_CHARS) or "(no message)",
        f" | stack: {stack}" if stack else "",
    )
    return True


def reset_rate_limits() -> None:
    """Test hook."""
    _recent.clear()

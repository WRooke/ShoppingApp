"""Logging setup: rotating file handler, console handler, and an in-memory
ring buffer that backs the /diagnostics log tail.

Format (per CLAUDE.md): ``%(asctime)s [%(levelname)s] %(name)s: %(message)s``
File: ``logs/app.log``, rotated daily, 14 days retained.
"""

from __future__ import annotations

import logging
import logging.handlers
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from app.config import settings

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Cap on how much of a traceback the ring buffer keeps per entry, so one huge traceback
# can't blow out the in-memory buffer's size — full tracebacks are still written to
# logs/app.log unbounded via the file handler below.
_MAX_TRACEBACK_CHARS = 4000

_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Newest entries are appended to the right. maxlen caps memory use — worst case is
# ~20MB (5000 entries × the 4000-char/entry traceback cap above). Raised from 1000 to 5000
# 2026-10-01 (diagnostics chunk 7.7, 5a) alongside removing /recent-errors' [:10] slice, so a
# burst of errors doesn't push genuinely recent ones out of the buffer before anyone's looked.
RING_BUFFER_MAXLEN = 5000
_ring: deque[dict] = deque(maxlen=RING_BUFFER_MAXLEN)


class RingBufferHandler(logging.Handler):
    """Keeps the most recent log records in memory as plain dicts."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            # The file handler gets the full traceback via exc_info=True, but until now the
            # ring buffer (and so the /diagnostics UI) silently dropped it, only ever showing
            # the one-line summary — undiagnosable without NUC filesystem access. Attach a
            # capped traceback here so an unhandled-exception entry is actually actionable
            # from the diagnostics page itself.
            if record.exc_info:
                tb = "".join(traceback.format_exception(*record.exc_info))
                if len(tb) > _MAX_TRACEBACK_CHARS:
                    tb = tb[:_MAX_TRACEBACK_CHARS] + "\n... (truncated)"
                entry["traceback"] = tb
            _ring.append(entry)
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)


def get_log_entries(limit: int = 200, level: str | None = None) -> list[dict]:
    """Return up to ``limit`` most-recent entries, newest first.

    ``level`` filters to that level and above (e.g. level='ERROR' also
    includes CRITICAL).
    """
    entries = list(_ring)
    if level:
        threshold = _LEVEL_ORDER.get(level.upper(), 0)
        entries = [e for e in entries if _LEVEL_ORDER.get(e["level"], 0) >= threshold]
    entries = entries[-limit:]
    entries.reverse()
    return entries


# WinError 10054 (WSAECONNRESET) constant, named rather than inlined so the filter below
# reads as "the specific Windows reset error" rather than a bare magic number.
_WSAECONNRESET = 10054


class _WinsockResetNoiseFilter(logging.Filter):
    """Downgrades the Proactor event loop's own WinError 10054 (ConnectionResetError)
    noise from ERROR to DEBUG, instead of dropping it outright (diagnostics chunk 7.7, 5d).

    On Windows, asyncio's ProactorEventLoop logs an ERROR via the ``asyncio`` logger
    whenever a client (a phone's browser going to sleep mid-request, a flaky WiFi drop on
    the household LAN) closes its TCP connection abruptly instead of a clean FIN — this is
    routine on a home network, not an application fault, and was flooding /diagnostics'
    Recent Errors card with entries that buried genuine errors underneath them.

    Matched on the exception object itself (``isinstance`` + its ``.winerror`` attribute),
    not a string search against the message — so it can't accidentally swallow an unrelated
    real connection error that happens to share wording. Only ``ConnectionResetError``
    records carrying exactly this Windows error code are touched; everything else, including
    every other kind of connection failure, passes through unchanged at its original level.

    Deliberately narrow (attached only to the ``asyncio`` logger, not root, and not a
    blanket ``loop.set_exception_handler()`` override) per CLAUDE.md's "comment the why"
    standard and the maintainer's explicit steer against anything broader.

    Downgrading to DEBUG — rather than returning False to drop the record — keeps it
    auditable: on a machine running with ``LOG_LEVEL=DEBUG`` the record still reaches
    ``app.log``/the ring buffer (re-gated here to the same threshold every other DEBUG
    record is already subject to via ``root.setLevel()``, since this one reaches that gate
    late — the record was already created at ERROR before this filter ever saw it); at any
    stricter level it's fully absent, same as any other DEBUG-level log line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc = record.exc_info[1]
            if isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == _WSAECONNRESET:
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
                return logging.getLogger().getEffectiveLevel() <= logging.DEBUG
        return True


_configured = False


def setup_logging() -> None:
    """Idempotent: safe to call more than once (e.g. under uvicorn reload)."""
    global _configured
    if _configured:
        return

    Path(settings.logs_path).mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    file_handler = logging.handlers.TimedRotatingFileHandler(
        Path(settings.logs_path) / "app.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    ring_handler = RingBufferHandler()
    root.addHandler(ring_handler)

    # Attached to the "asyncio" logger specifically (not root — see the filter's own
    # docstring for why a broader hook was deliberately rejected).
    logging.getLogger("asyncio").addFilter(_WinsockResetNoiseFilter())

    # uvicorn's access log stays at INFO (its default) rather than being quietened to
    # WARNING: CLAUDE.md > Security §4 explicitly wants "light access logging on
    # /api/v1/*" so an unfamiliar device's request pattern is visible, and uvicorn's
    # access log almost never emits above INFO — filtering to WARNING here would have
    # silently discarded it entirely rather than "quietening" it. Daily rotation + 14-day
    # retention (below) is what keeps this from growing unbounded, not a level filter.

    _configured = True
    logging.getLogger(__name__).info("Logging configured (level=%s)", settings.log_level)

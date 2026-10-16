"""Logging setup: rotating file handler, console handler, and in-memory
ring buffers that back the /diagnostics log tail.

Format (per CLAUDE.md): ``%(asctime)s [%(levelname)s] %(name)s: %(message)s``
File: ``logs/app.log``, rotated daily, 14 days retained.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
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

# One message can be arbitrarily large (a logged payload, a model reply). The file keeps the full
# line; the in-memory rings and the /diagnostics page get a bounded one.
_MAX_MESSAGE_CHARS = 2000

_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Newest entries are appended to the right. maxlen caps memory use — worst case is
# ~20MB (5000 entries × the 4000-char/entry traceback cap above). Raised from 1000 to 5000
# 2026-10-01 (the Status page fixes) alongside removing /recent-errors' [:10] slice, so a
# burst of errors doesn't push genuinely recent ones out of the buffer before anyone's looked.
RING_BUFFER_MAXLEN = 5000
_ring: deque[dict] = deque(maxlen=RING_BUFFER_MAXLEN)

# WARNING-and-above also go into their OWN, smaller ring (2026-10-07 logging audit). With
# everything in one ring, routine INFO traffic (every access line, the diagnostics page's own 5 s
# polling) evicted genuine errors within ~2 hours, so "Recent errors" went blank while the problem
# was still real. Errors are rare, so 500 of them is days of history; the INFO ring can churn
# without losing them.
ERROR_RING_MAXLEN = 500
_error_ring: deque[dict] = deque(maxlen=ERROR_RING_MAXLEN)

# --- redaction (2026-10-07 logging audit) ------------------------------------------------------
# Secrets must never reach app.log, the console or /diagnostics even if some code path formats one
# into an exception message or a debug dump (docs/security.md > AnyList credentials, Personal Data Policy). Two
# layers: (1) the configured credential VALUES, read from settings at call time so a key added
# later is covered, and (2) the Google API key shape, for a key that isn't the configured one.
# Applied in the formatter (file + console) and in the ring buffers.
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
_MIN_SECRET_LEN = 6  # anything shorter would start masking ordinary words


def redact(text: str) -> str:
    """Return ``text`` with configured credentials and Google-API-key-shaped strings masked."""
    if not text:
        return text
    for secret in (settings.gemini_api_key, settings.anylist_password, settings.anylist_email):
        if secret and len(secret) >= _MIN_SECRET_LEN and secret in text:
            text = text.replace(secret, "[redacted]")
    return _GOOGLE_KEY_RE.sub("[redacted]", text)


class _RedactingFormatter(logging.Formatter):
    """The standard format, run through `redact()` — covers the message AND any traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RingBufferHandler(logging.Handler):
    """Keeps the most recent log records in memory as plain dicts."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = redact(record.getMessage())
            if len(message) > _MAX_MESSAGE_CHARS:
                message = message[:_MAX_MESSAGE_CHARS] + f"... ({len(message)} chars, truncated)"
            entry = {
                "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
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
                entry["traceback"] = redact(tb)
            _ring.append(entry)
            if record.levelno >= logging.WARNING:
                _error_ring.append(entry)
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)


def get_log_entries(limit: int = 200, level: str | None = None) -> list[dict]:
    """Return up to ``limit`` most-recent entries, newest first.

    ``level`` filters to that level and above (e.g. level='ERROR' also
    includes CRITICAL). WARNING-and-above reads come from the dedicated error ring, so a flood of
    INFO lines can't have evicted them.
    """
    threshold = _LEVEL_ORDER.get(level.upper(), 0) if level else 0
    entries = list(_error_ring if threshold >= logging.WARNING else _ring)
    if threshold:
        entries = [e for e in entries if _LEVEL_ORDER.get(e["level"], 0) >= threshold]
    entries = entries[-limit:]
    entries.reverse()
    return entries


# WinError 10054 (WSAECONNRESET) constant, named rather than inlined so the filter below
# reads as "the specific Windows reset error" rather than a bare magic number.
_WSAECONNRESET = 10054


class _WinsockResetNoiseFilter(logging.Filter):
    """Downgrades the Proactor event loop's own WinError 10054 (ConnectionResetError)
    noise from ERROR to DEBUG, instead of dropping it outright (the Status page fixes).

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
    ``app.log``/the ring buffer (checked here against the same threshold every other DEBUG
    record is already subject to via ``root.setLevel()``; this record needs the explicit
    check because it was already created at ERROR before this filter ever saw it); at any
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


# Requests the app's own pages make on a timer (the diagnostics page polls every 5 s, the nav badge
# on every route change, capture/push progress every ~600 ms). Successful ones are demoted to DEBUG
# so they don't bury everything else; failures (status >= 400) and every other request keep their
# INFO line — docs/security.md > App-level protections still wants /api/v1 access visible.
_POLLING_PATH_PREFIXES = (
    "/api/v1/health",
    "/api/v1/diagnostics/status",
    "/api/v1/diagnostics/logs",
    "/api/v1/diagnostics/recent-errors",
    "/api/v1/recipes/capture/progress/",
    "/api/v1/checklist/push/progress/",
)


class _PollingAccessFilter(logging.Filter):
    """Downgrades successful polling access lines on ``uvicorn.access`` from INFO to DEBUG (same
    re-gating approach as `_WinsockResetNoiseFilter`). uvicorn's access record carries
    ``args = (client_addr, method, full_path, http_version, status_code)``."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            path, status = str(args[2]), args[4]
            if isinstance(status, int) and status < 400 and path.startswith(_POLLING_PATH_PREFIXES):
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
                return logging.getLogger().getEffectiveLevel() <= logging.DEBUG
        return True


_configured = False


def setup_logging(*, rotate: bool = True) -> None:
    """Idempotent: safe to call more than once (e.g. under uvicorn reload).

    ``rotate=False`` is for the short-lived helper scripts (backup/update/restore/verify_server),
    which append to the same ``app.log`` as the server but must never perform the midnight
    rollover themselves: on Windows two processes holding the file make the rename raise
    PermissionError and lose records (2026-10-07 logging audit). Only the server rotates."""
    global _configured
    if _configured:
        return

    Path(settings.logs_path).mkdir(parents=True, exist_ok=True)
    formatter = _RedactingFormatter(LOG_FORMAT)

    # An unrecognised LOG_LEVEL (a typo in .env) used to raise ValueError from setLevel() at
    # import, killing the app with nothing logged. Fall back to INFO and say so once handlers exist.
    bad_level = settings.log_level not in _LEVEL_ORDER
    level_name = "INFO" if bad_level else settings.log_level

    root = logging.getLogger()
    root.setLevel(level_name)
    root.handlers.clear()

    log_path = Path(settings.logs_path) / "app.log"
    if rotate:
        file_handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
            log_path, when="midnight", backupCount=14, encoding="utf-8"
        )
    else:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # A redirected console on a cp1252 box (Task Scheduler, start.bat) can't encode every character
    # a log line may carry; replace rather than letting the handler's error path drop the line.
    try:
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass  # not a reconfigurable text stream (e.g. pytest capture) — nothing to do
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    ring_handler = RingBufferHandler()
    root.addHandler(ring_handler)

    # Attached to the "asyncio" logger specifically (not root — see the filter's own
    # docstring for why a broader hook was deliberately rejected).
    logging.getLogger("asyncio").addFilter(_WinsockResetNoiseFilter())
    logging.getLogger("uvicorn.access").addFilter(_PollingAccessFilter())

    # uvicorn's access log stays at INFO (its default) rather than being quietened to
    # WARNING: docs/security.md > App-level protections explicitly wants "light access logging on
    # /api/v1/*" so an unfamiliar device's request pattern is visible, and uvicorn's
    # access log almost never emits above INFO — filtering to WARNING here would have
    # silently discarded it entirely rather than "quietening" it. Only the app's own
    # successful polling requests are demoted (see `_PollingAccessFilter`). Daily rotation +
    # 14-day retention is what keeps the rest from growing unbounded.

    _configured = True
    log = logging.getLogger(__name__)
    if bad_level:
        log.warning(
            "LOG_LEVEL=%r is not a valid level (use one of %s); using INFO",
            settings.log_level,
            ", ".join(_LEVEL_ORDER),
        )
    log.info("Logging configured (level=%s)", level_name)

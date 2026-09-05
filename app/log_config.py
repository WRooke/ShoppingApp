"""Logging setup: rotating file handler, console handler, and an in-memory
ring buffer that backs the /diagnostics log tail.

Format (per CLAUDE.md): ``%(asctime)s [%(levelname)s] %(name)s: %(message)s``
File: ``logs/app.log``, rotated daily, 14 days retained.
"""

from __future__ import annotations

import logging
import logging.handlers
from collections import deque
from datetime import datetime
from pathlib import Path

from app.config import settings

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Newest entries are appended to the right. maxlen caps memory use.
_ring: deque[dict] = deque(maxlen=1000)


class RingBufferHandler(logging.Handler):
    """Keeps the most recent log records in memory as plain dicts."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _ring.append(
                {
                    "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )
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

    # uvicorn's access log is noisy at INFO; keep it but quieten it.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("Logging configured (level=%s)", settings.log_level)

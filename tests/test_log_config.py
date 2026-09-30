"""Tests for app/log_config.py's WinError 10054 noise filter — see CLAUDE.md > Diagnostics &
Logging and docs/diagnostics-and-logging.md. Diagnostics chunk 7.7, 5d.

Exercises `_WinsockResetNoiseFilter` directly rather than round-tripping a real socket error,
since triggering an actual Proactor WSAECONNRESET deterministically in a test is impractical —
the filter's own logic (exception-type + winerror match) is what's under test here.
"""

from __future__ import annotations

import logging

from app.log_config import _WinsockResetNoiseFilter


def _make_record(exc: BaseException | None) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    record = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        args=(),
        exc_info=exc_info,
    )
    return record


def test_matching_winerror_10054_record_is_downgraded_to_debug():
    exc = ConnectionResetError("An existing connection was forcibly closed by the remote host")
    exc.winerror = 10054
    record = _make_record(exc)

    keep = _WinsockResetNoiseFilter().filter(record)

    assert record.levelno == logging.DEBUG
    assert record.levelname == "DEBUG"
    # Whether it's kept depends on the currently configured root level (re-gated the same as
    # any other DEBUG record) — not asserted here; see the effective-level test below.
    assert keep in (True, False)


def test_matching_record_kept_only_when_root_level_permits_debug(monkeypatch):
    exc = ConnectionResetError("reset")
    exc.winerror = 10054

    monkeypatch.setattr(logging.getLogger(), "level", logging.DEBUG)
    assert _WinsockResetNoiseFilter().filter(_make_record(exc)) is True

    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    assert _WinsockResetNoiseFilter().filter(_make_record(exc)) is False


def test_non_matching_exception_type_is_untouched():
    exc = TimeoutError("some other connection failure")
    record = _make_record(exc)

    keep = _WinsockResetNoiseFilter().filter(record)

    assert keep is True
    assert record.levelno == logging.ERROR
    assert record.levelname == "ERROR"


def test_connection_reset_with_a_different_winerror_is_untouched():
    """Guards against over-matching on exception type alone — only WinError 10054
    specifically is downgraded, not every ConnectionResetError."""
    exc = ConnectionResetError("a different reset")
    exc.winerror = 10053  # WSAECONNABORTED, a different code entirely
    record = _make_record(exc)

    keep = _WinsockResetNoiseFilter().filter(record)

    assert keep is True
    assert record.levelno == logging.ERROR


def test_record_with_no_exc_info_is_untouched():
    record = _make_record(None)

    keep = _WinsockResetNoiseFilter().filter(record)

    assert keep is True
    assert record.levelno == logging.ERROR

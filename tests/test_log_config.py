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


# --- 2026-10-07 logging audit: error ring, redaction, polling noise, message cap ---------------

import pytest  # noqa: E402

from app import log_config  # noqa: E402


@pytest.fixture()
def rings(monkeypatch):
    """Isolated, empty rings so these tests can't see (or disturb) the session's real entries."""
    from collections import deque

    monkeypatch.setattr(log_config, "_ring", deque(maxlen=50))
    monkeypatch.setattr(log_config, "_error_ring", deque(maxlen=5))
    return log_config


def _emit(level: int, msg: str, *, exc: BaseException | None = None) -> None:
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    record = logging.LogRecord("app.test", level, __file__, 1, msg, (), exc_info)
    log_config.RingBufferHandler().emit(record)


def test_errors_survive_an_info_flood_in_their_own_ring(rings):
    _emit(logging.ERROR, "the one that matters")
    for i in range(200):  # far more than the INFO ring holds
        _emit(logging.INFO, f"access line {i}")

    errors = log_config.get_log_entries(limit=10, level="ERROR")
    assert [e["message"] for e in errors] == ["the one that matters"]
    # the INFO ring really did evict it, so the dedicated ring is what saved it
    assert all(e["message"] != "the one that matters" for e in list(log_config._ring))


def test_ring_message_is_capped_but_says_how_long_it_was(rings):
    _emit(logging.INFO, "x" * 10_000)
    (entry,) = log_config.get_log_entries(limit=1)
    assert len(entry["message"]) < 2200 and "10000 chars, truncated" in entry["message"]


def test_secrets_are_redacted_from_message_and_traceback(rings, monkeypatch):
    monkeypatch.setattr(log_config.settings, "gemini_api_key", "super-secret-gemini-key-123", raising=False)
    monkeypatch.setattr(log_config.settings, "anylist_password", "hunter2-hunter2", raising=False)
    shaped = "AIza" + "B" * 35
    try:
        raise RuntimeError("boom super-secret-gemini-key-123")
    except RuntimeError as exc:
        _emit(logging.ERROR, f"call failed key={shaped} pw=hunter2-hunter2", exc=exc)

    (entry,) = log_config.get_log_entries(limit=1)
    blob = entry["message"] + entry["traceback"]
    for secret in ("super-secret-gemini-key-123", "hunter2-hunter2", shaped):
        assert secret not in blob
    assert "[redacted]" in blob


def test_redacting_formatter_covers_the_file_and_console_line(monkeypatch):
    monkeypatch.setattr(log_config.settings, "anylist_email", "someone@example.test", raising=False)
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "login as someone@example.test", (), None)
    line = log_config._RedactingFormatter(log_config.LOG_FORMAT).format(record)
    assert "someone@example.test" not in line and "[redacted]" in line


def _access(path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", path, "1.1", status), None,
    )


def test_successful_polling_requests_are_demoted_but_failures_and_others_are_not():
    f = log_config._PollingAccessFilter()
    polled = _access("/api/v1/diagnostics/status", 200)
    f.filter(polled)
    assert polled.levelno == logging.DEBUG

    failed = _access("/api/v1/diagnostics/status", 500)
    assert f.filter(failed) is True and failed.levelno == logging.INFO

    other = _access("/api/v1/recipes", 200)
    assert f.filter(other) is True and other.levelno == logging.INFO

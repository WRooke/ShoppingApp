"""Unit tests for app/services/progress_tracker.py — see CLAUDE.md > UI/UX > Real progress
indicators. Pure in-memory state, no DB/network.
"""

from __future__ import annotations

import time

from app.services import progress_tracker


def setup_function():
    # Module-level dict — clear it between tests so one test's tokens can't leak into another.
    progress_tracker._progress.clear()


def test_start_registers_all_steps_pending():
    progress_tracker.start("tok1", ["a", "b", "c"])
    steps = progress_tracker.get("tok1")
    assert steps == [
        {"name": "a", "status": "pending", "detail": None},
        {"name": "b", "status": "pending", "detail": None},
        {"name": "c", "status": "pending", "detail": None},
    ]


def test_step_active_then_done():
    progress_tracker.start("tok2", ["a", "b"])
    progress_tracker.step_active("tok2", "a")
    steps = progress_tracker.get("tok2")
    assert steps[0]["status"] == "active"
    assert steps[1]["status"] == "pending"

    progress_tracker.step_done("tok2", "a")
    steps = progress_tracker.get("tok2")
    assert steps[0]["status"] == "done"


def test_step_failed_records_detail():
    progress_tracker.start("tok3", ["a"])
    progress_tracker.step_active("tok3", "a")
    progress_tracker.step_failed("tok3", "a", "boom")
    steps = progress_tracker.get("tok3")
    assert steps[0]["status"] == "failed"
    assert steps[0]["detail"] == "boom"


def test_get_unknown_token_returns_none():
    assert progress_tracker.get("never-started") is None


def test_falsy_token_is_a_no_op_throughout():
    # None/"" tokens must never raise or create an entry — the normal case for any caller
    # that didn't opt into progress tracking (e.g. the capture_queue retry poller).
    progress_tracker.start(None, ["a"])
    progress_tracker.step_active(None, "a")
    progress_tracker.step_done(None, "a")
    progress_tracker.step_failed(None, "a", "x")
    assert progress_tracker.get(None) is None
    assert progress_tracker.get("") is None
    assert progress_tracker._progress == {}


def test_updates_to_unknown_token_are_silently_ignored():
    # A step_* call after the entry expired (or for a token that was never start()ed) must
    # not raise — same "don't crash the real operation over a UI nicety" discipline as the
    # falsy-token case.
    progress_tracker.step_active("ghost", "a")
    progress_tracker.step_done("ghost", "a")
    progress_tracker.step_failed("ghost", "a", "x")
    assert progress_tracker.get("ghost") is None


def test_expired_entries_are_swept_on_next_start():
    progress_tracker.start("old", ["a"])
    progress_tracker._progress["old"].updated_at = time.monotonic() - progress_tracker._TTL_SECONDS - 1
    progress_tracker.start("new", ["b"])  # triggers the sweep
    assert progress_tracker.get("old") is None
    assert progress_tracker.get("new") is not None

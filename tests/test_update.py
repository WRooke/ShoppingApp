"""Unit tests for scripts/update.py > _server_is_running() — the 2026-09-13 code review's
live-migration pre-flight check. subprocess.run is mocked; no real PowerShell/process
inspection happens in the test suite (CLAUDE.md > Code Architecture & Maintainability).

The rest of update.py (git pull / pip install / alembic orchestration) is ops-script
behaviour verified by hand against the real NUC workflow, not unit-tested — same standing as
scripts/backup.py and scripts/deploy.py.
"""

from __future__ import annotations

import subprocess

from scripts.update import _server_is_running


class _Result:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_server_is_running_true_when_a_process_is_found(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Result(0, "1\r\n")
    )
    assert _server_is_running() is True


def test_server_is_running_false_when_count_is_zero(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Result(0, "0\r\n")
    )
    assert _server_is_running() is False


def test_server_is_running_false_when_powershell_fails(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Result(1, "")
    )
    assert _server_is_running() is False


def test_server_is_running_false_and_does_not_raise_on_exception(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("powershell not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert _server_is_running() is False

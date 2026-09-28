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


# --- 2026-09-28: backups/ must never block an update ------------------------------------
# Real (throwaway) git repos, not mocks: the bug was in how git itself reports this state.

import subprocess as _sp  # noqa: E402  (kept next to its only users)

from scripts.update import dirty_status_ignoring_backups  # noqa: E402


def _git(cwd, *args):
    _sp.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.txt").write_text("code")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / ".gitkeep").write_text("")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_staged_then_deleted_backup_does_not_count_as_dirty(tmp_path):
    """The exact production state: `AD backups/x.db` (staged add, then deleted on disk)."""
    repo = _repo(tmp_path)
    backup = repo / "backups" / "mealplanner_x.db"
    backup.write_text("db")
    _git(repo, "add", "backups")
    backup.unlink()

    ok, out = dirty_status_ignoring_backups(repo)
    assert ok and out == ""


def test_real_local_edit_outside_backups_still_counts_as_dirty(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.txt").write_text("edited on the NUC")
    (repo / "backups" / "mealplanner_x.db").write_text("db")

    ok, out = dirty_status_ignoring_backups(repo)
    assert ok and "app.txt" in out and "backups" not in out

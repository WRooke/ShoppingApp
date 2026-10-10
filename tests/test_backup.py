"""Unit tests for scripts/backup.py's DB-copy mechanism — no DB/network beyond throwaway
SQLite files in a pytest tmp_path (CLAUDE.md > Code Architecture & Maintainability).

Only `_backup_db_file` and `dump_db_to_json` are tested directly: the rest of
`run_backup()` (trimming, git commit/push) is ops-script behaviour verified by hand per the
project's own "restore path actually tested once" standard (CLAUDE.md > Backup & Restore),
not unit-tested.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts.backup import _backup_db_file, dump_db_to_json


def _make_db(path, *, wal: bool = False) -> None:
    con = sqlite3.connect(str(path))
    try:
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        con.execute("INSERT INTO widgets (name) VALUES ('a'), ('b')")
        con.commit()
    finally:
        con.close()


def test_backup_db_file_copies_content_and_passes_integrity_check(tmp_path):
    source = tmp_path / "source.db"
    dest = tmp_path / "backup.db"
    _make_db(source)

    _backup_db_file(source, dest)

    assert dest.exists()
    con = sqlite3.connect(str(dest))
    try:
        rows = con.execute("SELECT name FROM widgets ORDER BY id").fetchall()
        assert rows == [("a",), ("b",)]
    finally:
        con.close()


def test_backup_db_file_works_against_a_wal_mode_source(tmp_path):
    """2026-09-13 code review: the whole point of switching off shutil.copy2 was safety against
    a live, possibly WAL-mode database (see app/database.py) — the online backup API must fold
    WAL content into a single consistent file regardless of the source's journal mode."""
    source = tmp_path / "source.db"
    dest = tmp_path / "backup.db"
    _make_db(source, wal=True)

    _backup_db_file(source, dest)

    con = sqlite3.connect(str(dest))
    try:
        rows = con.execute("SELECT name FROM widgets ORDER BY id").fetchall()
        assert rows == [("a",), ("b",)]
    finally:
        con.close()


def test_backup_db_file_raises_and_cleans_up_on_a_corrupt_result(tmp_path, monkeypatch):
    """A failed integrity check must fail loudly (per the module docstring's "catch a bad
    backup at backup time, not the day it's needed for a restore") and not leave a corrupt
    file behind under the backup name."""
    source = tmp_path / "source.db"
    dest = tmp_path / "backup.db"
    _make_db(source)

    class _FakeCursor:
        def fetchone(self):
            return ("corruption found",)

    class _FakeConnection:
        def __init__(self, *a, **k):
            pass

        def backup(self, other):
            pass

        def execute(self, *a, **k):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr("scripts.backup.sqlite3.connect", lambda *a, **k: _FakeConnection())
    with pytest.raises(RuntimeError, match="integrity check failed"):
        _backup_db_file(source, dest)
    assert not dest.exists()


def test_dump_db_to_json_reads_every_table(tmp_path):
    source = tmp_path / "source.db"
    _make_db(source)

    dump = dump_db_to_json(source)

    assert dump == {"widgets": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}


# --- a failed git commit/push is a failed run (2026-10-07 logging audit) ----------------------


def test_strict_backup_raises_after_saving_when_the_git_step_fails(tmp_path, monkeypatch, caplog):
    """Task Scheduler judges success by exit code. The backup FILE is written either way, but if
    committing/pushing it failed the off-machine copy is stale, so the run must not look green."""
    import logging

    from scripts import backup

    source = tmp_path / "live.db"
    _make_db(source)
    monkeypatch.setattr(backup.settings, "database_path", str(source), raising=False)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "commit_and_push", lambda: False)

    with caplog.at_level(logging.INFO):
        with pytest.raises(backup.BackupGitError):
            backup.run_backup(strict=True)

    assert list((tmp_path / "backups").glob("mealplanner_*.db")), "the backup file must still be saved"
    assert "was NOT committed/pushed" in caplog.text
    # the non-strict (programmatic) call still just returns the saved file
    assert backup.run_backup().exists()

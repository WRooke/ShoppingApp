"""Migration tests for Fix 2 (aliases feed the extraction prompt) — F2.1 (the
`ingredient_aliases.source` column) and F2.2 (seeding the 3 legacy system alias groups).

Same `alembic upgrade` -> temp SQLite DB pattern as `test_ingredient_name_backfill_migration.py`
(Fix 1's own migration tests). CLAUDE.md non-negotiable rule 3 (data loss on prod is never
acceptable): F2.1 asserts row count is unchanged and every existing row's other columns are
byte-identical; F2.2 is a deliberate, documented exception (it *adds* rows) and asserts the
count increases by exactly the number of rows it seeds, never decreases, per the
ingredient-name-matching plan's Testing & Verification section.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import config as app_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PRE_F21 = "bcaf5b44af53"  # chain tip as of Fix 1 (F1.5), just before F2.1
_F21_HEAD = "092f6bb91c9c"  # F2.1 — ingredient_aliases.source column
_F22_HEAD = "62a354151f0d"  # F2.2 — seed the 3 legacy system alias groups

_EXPECTED_SYSTEM_PAIRS = {
    ("table salt", "salt"),
    ("cooking salt", "salt"),
    ("kosher salt", "salt"),
    ("sea salt", "salt"),
    ("minced beef", "beef mince"),
    ("green onion", "spring onion"),
    ("scallion", "spring onion"),
}


def _upgrade_to(db_path: Path, monkeypatch, revision: str) -> None:
    monkeypatch.setattr(app_config.settings, "database_path", str(db_path))
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, revision)


def _downgrade_to(db_path: Path, monkeypatch, revision: str) -> None:
    monkeypatch.setattr(app_config.settings, "database_path", str(db_path))
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, revision)


@pytest.fixture()
def conn_factory(tmp_path):
    db_path = tmp_path / "fix2_migration_test.db"

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return db_path, _connect


def _row_count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- F2.1: ingredient_aliases.source column ------------------------------------------


def test_source_column_added_with_user_default_no_data_loss(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F21)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO ingredient_aliases "
            "(alias_name, canonical_name, note, created_at, updated_at) VALUES "
            "('canola oil', 'vegetable oil', 'pre-existing row', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before = dict(
            conn.execute(
                "SELECT id, alias_name, canonical_name, note FROM ingredient_aliases "
                "WHERE alias_name='canola oil'"
            ).fetchone()
        )
        before_count = _row_count(conn, "ingredient_aliases")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F21_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "ingredient_aliases") == before_count  # rule 3 — no data loss
        after = dict(
            conn.execute(
                "SELECT id, alias_name, canonical_name, note, source FROM ingredient_aliases "
                "WHERE alias_name='canola oil'"
            ).fetchone()
        )
        assert after["id"] == before["id"]
        assert after["alias_name"] == before["alias_name"]
        assert after["canonical_name"] == before["canonical_name"]
        assert after["note"] == before["note"]
        assert after["source"] == "user"  # server_default applied to the pre-existing row
    finally:
        conn.close()


# --- F2.2: seed the 3 legacy system alias groups (7 rows) ----------------------------------


def test_seeds_exactly_the_7_expected_system_rows(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _F21_HEAD)

    conn = connect()
    try:
        before_count = _row_count(conn, "ingredient_aliases")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F22_HEAD)

    conn = connect()
    try:
        after_count = _row_count(conn, "ingredient_aliases")
        # rule 3's one legitimate exception: count increases by exactly 7, never decreases.
        assert after_count == before_count + 7
        rows = conn.execute(
            "SELECT alias_name, canonical_name, source FROM ingredient_aliases "
            "WHERE source = 'system'"
        ).fetchall()
        assert len(rows) == 7
        assert {(r["alias_name"], r["canonical_name"]) for r in rows} == _EXPECTED_SYSTEM_PAIRS
        assert all(r["source"] == "system" for r in rows)
    finally:
        conn.close()


def test_collision_with_an_existing_user_alias_is_skipped_not_crashed(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _F21_HEAD)

    conn = connect()
    try:
        # A household already grouped "scallion" under something else via Settings, before
        # this migration ever ran.
        conn.execute(
            "INSERT INTO ingredient_aliases "
            "(alias_name, canonical_name, source, created_at, updated_at) VALUES "
            "('scallion', 'zz household canonical', 'user', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "ingredient_aliases")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F22_HEAD)  # must not raise

    conn = connect()
    try:
        # Exactly 6 (not 7) new system rows -- "scallion" was skipped.
        after_count = _row_count(conn, "ingredient_aliases")
        assert after_count == before_count + 6
        scallion_rows = conn.execute(
            "SELECT alias_name, canonical_name, source FROM ingredient_aliases "
            "WHERE alias_name = 'scallion'"
        ).fetchall()
        assert len(scallion_rows) == 1  # never duplicated, never overwritten
        assert dict(scallion_rows[0]) == {
            "alias_name": "scallion",
            "canonical_name": "zz household canonical",
            "source": "user",
        }
        # The other 6 pairs still seeded normally.
        system_rows = {
            (r["alias_name"], r["canonical_name"])
            for r in conn.execute(
                "SELECT alias_name, canonical_name FROM ingredient_aliases WHERE source='system'"
            ).fetchall()
        }
        assert system_rows == _EXPECTED_SYSTEM_PAIRS - {("scallion", "spring onion")}
    finally:
        conn.close()


def test_downgrade_removes_only_the_7_system_rows(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _F21_HEAD)

    conn = connect()
    try:
        # An unrelated F0-style user row that happens to already exist.
        conn.execute(
            "INSERT INTO ingredient_aliases "
            "(alias_name, canonical_name, source, created_at, updated_at) VALUES "
            "('heavy cream', 'thickened cream', 'user', datetime('now'), datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F22_HEAD)
    _downgrade_to(db_path, monkeypatch, _F21_HEAD)  # downgrade back to just before F2.2

    conn = connect()
    try:
        assert _row_count(conn, "ingredient_aliases") == 1
        remaining = dict(conn.execute("SELECT alias_name, source FROM ingredient_aliases").fetchone())
        assert remaining == {"alias_name": "heavy cream", "source": "user"}
    finally:
        conn.close()

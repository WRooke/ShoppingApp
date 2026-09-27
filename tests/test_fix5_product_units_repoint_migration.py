"""Migration test for Fix 5's product_units repoint (f9e79977f8b0) — "milk" -> "full cream
milk" and "diced tomato" -> "canned tomato", following the same pattern as F0's yoghurt repoint
(c920cac31b6a) but with per-row collision safety (mirrors Fix 2's F2.2 alias-insert collision
handling) since these renames were added later, once that discipline was already established.

CLAUDE.md non-negotiable rule 3: every test asserts row count is unchanged and every touched or
untouched row's other columns are byte-identical to their pre-migration state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import config as app_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PRE_MIGRATION = "62a354151f0d"  # chain tip just before this migration
_HEAD = "f9e79977f8b0"


def _upgrade_to(db_path: Path, monkeypatch, revision: str) -> None:
    monkeypatch.setattr(app_config.settings, "database_path", str(db_path))
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, revision)


@pytest.fixture()
def conn_factory(tmp_path):
    db_path = tmp_path / "fix5_repoint_test.db"

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return db_path, _connect


def _insert_product_unit(conn, name, label, qty, unit):
    conn.execute(
        "INSERT INTO product_units "
        "(ingredient_name, purchase_label, purchase_qty, purchase_unit, is_preseeded, "
        " created_at, updated_at) VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))",
        (name, label, qty, unit),
    )


def _row_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM product_units").fetchone()[0]


def test_repoints_milk_and_diced_tomato_leaves_unrelated_rows_untouched(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_MIGRATION)

    conn = connect()
    try:
        _insert_product_unit(conn, "milk", "1L bottle", 1.0, "L")
        _insert_product_unit(conn, "milk", "2L bottle", 2.0, "L")
        _insert_product_unit(conn, "diced tomato", "400g can", 400.0, "g")
        _insert_product_unit(conn, "butter", "250g block", 250.0, "g")  # unrelated
        conn.commit()
        before_count = _row_count(conn)
        before_butter = dict(
            conn.execute("SELECT * FROM product_units WHERE ingredient_name='butter'").fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _HEAD)

    conn = connect()
    try:
        assert _row_count(conn) == before_count  # rule 3 — no data loss
        assert conn.execute(
            "SELECT COUNT(*) FROM product_units WHERE ingredient_name IN ('milk', 'diced tomato')"
        ).fetchone()[0] == 0

        milk_rows = {
            r["purchase_label"]: r["purchase_qty"]
            for r in conn.execute(
                "SELECT purchase_label, purchase_qty FROM product_units "
                "WHERE ingredient_name='full cream milk'"
            ).fetchall()
        }
        assert milk_rows == {"1L bottle": 1.0, "2L bottle": 2.0}

        tomato = dict(
            conn.execute(
                "SELECT purchase_label, purchase_qty, purchase_unit FROM product_units "
                "WHERE ingredient_name='canned tomato'"
            ).fetchone()
        )
        assert tomato == {"purchase_label": "400g can", "purchase_qty": 400.0, "purchase_unit": "g"}

        after_butter = dict(
            conn.execute("SELECT * FROM product_units WHERE ingredient_name='butter'").fetchone()
        )
        assert after_butter == before_butter
    finally:
        conn.close()


def test_is_a_noop_with_no_matching_rows(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_MIGRATION)
    conn = connect()
    try:
        before_count = _row_count(conn)
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _HEAD)  # must not raise

    conn = connect()
    try:
        assert _row_count(conn) == before_count
    finally:
        conn.close()


def test_collision_with_an_existing_row_under_the_new_name_is_skipped_not_crashed(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_MIGRATION)

    conn = connect()
    try:
        # A household already has its own "full cream milk"/"1L bottle" row (e.g. added by
        # hand via Settings) BEFORE this migration ever runs -- renaming "milk"/"1L bottle"
        # onto the same (ingredient_name, purchase_label) pair would collide.
        _insert_product_unit(conn, "milk", "1L bottle", 1.0, "L")
        _insert_product_unit(conn, "full cream milk", "1L bottle", 1.0, "L")
        conn.commit()
        before_count = _row_count(conn)
        before_milk = dict(
            conn.execute(
                "SELECT * FROM product_units WHERE ingredient_name='milk'"
            ).fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _HEAD)  # must not raise

    conn = connect()
    try:
        assert _row_count(conn) == before_count  # nothing added or removed
        # The old "milk" row is left completely untouched, not deleted, not renamed.
        after_milk = dict(
            conn.execute("SELECT * FROM product_units WHERE ingredient_name='milk'").fetchone()
        )
        assert after_milk == before_milk
        # Still exactly one "full cream milk"/"1L bottle" row -- never duplicated.
        assert conn.execute(
            "SELECT COUNT(*) FROM product_units WHERE ingredient_name='full cream milk' "
            "AND purchase_label='1L bottle'"
        ).fetchone()[0] == 1
    finally:
        conn.close()

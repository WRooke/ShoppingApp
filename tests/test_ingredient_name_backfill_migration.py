"""Migration tests for the ingredient-name-matching plan's data migrations. Uses the same
`alembic upgrade` -> temp SQLite DB pattern already established in test_migrations.py.

CLAUDE.md non-negotiable rule 3 (data loss on prod is never acceptable, added 2026-09-27): every
test here asserts row counts are unchanged (or increase by exactly what a migration intends to
add) and that untouched rows are byte-for-byte identical to their pre-migration state -- this is
the automated check the ingredient-name-matching plan's Testing & Verification section calls for,
not just an eyeballed review.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import config as app_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _upgrade_to(db_path: Path, monkeypatch, revision: str) -> None:
    monkeypatch.setattr(app_config.settings, "database_path", str(db_path))
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, revision)


@pytest.fixture()
def conn_factory(tmp_path):
    db_path = tmp_path / "migration_test.db"

    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return db_path, _connect


# --- F0: repoint orphaned "yoghurt" product_units rows ------------------------------


def test_repoint_yoghurt_product_units_renames_only_the_name_column(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, "e62ee59a3bdc")  # just before this migration

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO product_units "
            "(ingredient_name, purchase_label, purchase_qty, purchase_unit, is_preseeded, "
            " created_at, updated_at) "
            "VALUES ('yoghurt', '1kg tub', 1000.0, 'g', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO product_units "
            "(ingredient_name, purchase_label, purchase_qty, purchase_unit, is_preseeded, "
            " created_at, updated_at) "
            "VALUES ('yoghurt', '500g tub', 500.0, 'g', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO product_units "
            "(ingredient_name, purchase_label, purchase_qty, purchase_unit, is_preseeded, "
            " created_at, updated_at) "
            "VALUES ('milk', '1L bottle', 1.0, 'L', 1, datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = conn.execute("SELECT COUNT(*) FROM product_units").fetchone()[0]
        before_milk = dict(
            conn.execute("SELECT * FROM product_units WHERE ingredient_name='milk'").fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, "c920cac31b6a")

    conn = connect()
    try:
        after_count = conn.execute("SELECT COUNT(*) FROM product_units").fetchone()[0]
        assert after_count == before_count, "migration must never add or remove rows"

        yoghurt_left = conn.execute(
            "SELECT COUNT(*) FROM product_units WHERE ingredient_name='yoghurt'"
        ).fetchone()[0]
        assert yoghurt_left == 0, "both yoghurt rows should have been renamed"

        renamed = conn.execute(
            "SELECT purchase_label, purchase_qty, purchase_unit, is_preseeded "
            "FROM product_units WHERE ingredient_name='greek yoghurt' ORDER BY purchase_label"
        ).fetchall()
        assert [dict(r) for r in renamed] == [
            {
                "purchase_label": "1kg tub",
                "purchase_qty": 1000.0,
                "purchase_unit": "g",
                "is_preseeded": 1,
            },
            {
                "purchase_label": "500g tub",
                "purchase_qty": 500.0,
                "purchase_unit": "g",
                "is_preseeded": 1,
            },
        ]

        # An unrelated row must be completely untouched.
        after_milk = dict(
            conn.execute("SELECT * FROM product_units WHERE ingredient_name='milk'").fetchone()
        )
        assert after_milk == before_milk
    finally:
        conn.close()


def test_repoint_yoghurt_product_units_is_a_noop_with_no_matching_rows(conn_factory, monkeypatch):
    """A fresh DB (or one that never had a bare "yoghurt" row) must migrate cleanly, not error."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, "e62ee59a3bdc")

    conn = connect()
    try:
        before_count = conn.execute("SELECT COUNT(*) FROM product_units").fetchone()[0]
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, "c920cac31b6a")

    conn = connect()
    try:
        after_count = conn.execute("SELECT COUNT(*) FROM product_units").fetchone()[0]
        assert after_count == before_count
    finally:
        conn.close()


# --- F1.5: backfill normalisation across the 5 reference tables --------------------------
# CLAUDE.md non-negotiable rule 3: every test below asserts row COUNT is unchanged and that
# every left-behind row is byte-for-byte identical to its pre-migration state.

_F0_HEAD = "bcaf5b44af53"  # chain tip as of this migration
_PRE_F15 = "c920cac31b6a"  # just before F1.5's own migration


def _row_count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_backfill_product_units_real_chicken_thigh_collision(conn_factory, monkeypatch):
    """The confirmed real prod duplicate: 'chicken thigh' and 'chicken thighs', identical
    500g-pack config, seeded as two separate is_preseeded rows."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO product_units (ingredient_name, purchase_label, purchase_qty, "
            "purchase_unit, is_preseeded, created_at, updated_at) VALUES "
            "('chicken thigh', '500g pack', 500.0, 'g', 1, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO product_units (ingredient_name, purchase_label, purchase_qty, "
            "purchase_unit, is_preseeded, created_at, updated_at) VALUES "
            "('chicken thighs', '500g pack', 500.0, 'g', 1, datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "product_units")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "product_units") == before_count, "no row may be dropped"
        kept = conn.execute(
            "SELECT COUNT(*) FROM product_units WHERE ingredient_name='chicken thigh'"
        ).fetchone()[0]
        left_behind = conn.execute(
            "SELECT COUNT(*) FROM product_units WHERE ingredient_name='chicken thighs'"
        ).fetchone()[0]
        # Both rows are pre-seeded and identical, so the tie-break is lowest id — the
        # already-singular "chicken thigh" row (inserted first) is kept, the plural is the
        # one left behind, untouched.
        assert kept == 1
        assert left_behind == 1
    finally:
        conn.close()


def test_backfill_coarse_ingredients_collision_keeps_lowest_id(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO coarse_ingredients (name, purchase_label, recipes_per_pack, "
            "created_at, updated_at) VALUES "
            "('coriander', 'bunch', 3, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO coarse_ingredients (name, purchase_label, recipes_per_pack, "
            "created_at, updated_at) VALUES "
            "('corianders', 'big bunch', 5, datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "coarse_ingredients")
        before_left = dict(
            conn.execute(
                "SELECT * FROM coarse_ingredients WHERE name='corianders'"
            ).fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "coarse_ingredients") == before_count
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM coarse_ingredients WHERE name='coriander'"
            ).fetchone()[0]
            == 1
        )
        # The plural row is left behind, completely untouched — including its own,
        # different, never-auto-merged recipes_per_pack/purchase_label config.
        after_left = dict(
            conn.execute(
                "SELECT * FROM coarse_ingredients WHERE name='corianders'"
            ).fetchone()
        )
        assert after_left == before_left
    finally:
        conn.close()


def test_backfill_usual_items_collision_prefers_row_with_last_added_at(conn_factory, monkeypatch):
    """Neither raw name is already in final normalised form (a hyphen and a plural
    respectively) — both actually need renaming, so this genuinely exercises the tie-break,
    unlike a case where one row already holds the target value verbatim (see the generic
    helper's "already_correct" guard, which must always win over any tie-break — a real bug
    caught while writing this migration)."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO usual_items (name, cadence_days, last_added_at, created_at, "
            "updated_at) VALUES "
            "('Ginger-Beer', 14, NULL, datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO usual_items (name, cadence_days, last_added_at, created_at, "
            "updated_at) VALUES "
            "('ginger beers', 14, datetime('now'), datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "usual_items")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "usual_items") == before_count
        kept = conn.execute(
            "SELECT last_added_at FROM usual_items WHERE name='ginger beer'"
        ).fetchone()
        assert kept is not None and kept[0] is not None  # the used row was the one kept
        # Left behind, completely untouched — still its original, un-normalised raw spelling.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM usual_items WHERE name='Ginger-Beer'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_backfill_ingredient_aliases_alias_name_collision(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO ingredient_aliases (alias_name, canonical_name, created_at, "
            "updated_at) VALUES "
            "('canola oil', 'vegetable oil', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO ingredient_aliases (alias_name, canonical_name, created_at, "
            "updated_at) VALUES "
            "('canola oils', 'olive oil', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "ingredient_aliases")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "ingredient_aliases") == before_count
        # Lowest id ("canola oil") keeps the normalised spelling; the plural is left behind
        # completely untouched, including its own (different) canonical_name.
        left = dict(
            conn.execute(
                "SELECT alias_name, canonical_name FROM ingredient_aliases "
                "WHERE alias_name='canola oils'"
            ).fetchone()
        )
        assert left == {"alias_name": "canola oils", "canonical_name": "olive oil"}
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ingredient_aliases WHERE alias_name='canola oil'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_backfill_ingredient_aliases_canonical_name_merges_freely(conn_factory, monkeypatch):
    """canonical_name has no uniqueness constraint, so — unlike alias_name — a collision here
    can rename EVERY matching row, not just one; two differently-spelled canonical targets
    that normalise the same way correctly end up pointing at one consistent spelling."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO ingredient_aliases (alias_name, canonical_name, created_at, "
            "updated_at) VALUES "
            "('oil spray', 'vegetable oil', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO ingredient_aliases (alias_name, canonical_name, created_at, "
            "updated_at) VALUES "
            "('cooking spray', 'vegetable oils', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "ingredient_aliases")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "ingredient_aliases") == before_count
        canonicals = {
            r[0]
            for r in conn.execute(
                "SELECT canonical_name FROM ingredient_aliases "
                "WHERE alias_name IN ('oil spray', 'cooking spray')"
            )
        }
        assert canonicals == {"vegetable oil"}, "both should converge on one spelling"
    finally:
        conn.close()


def test_backfill_ingredient_aliases_self_alias_guard(conn_factory, monkeypatch):
    """A row whose alias_name and canonical_name would become equal after normalising must be
    left completely untouched (not deleted, not partially renamed) — never a self-alias."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO ingredient_aliases (alias_name, canonical_name, created_at, "
            "updated_at) VALUES "
            "('spring onions', 'spring onion', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "ingredient_aliases")
        before_row = dict(
            conn.execute(
                "SELECT * FROM ingredient_aliases WHERE alias_name='spring onions'"
            ).fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "ingredient_aliases") == before_count
        after_row = dict(
            conn.execute(
                "SELECT * FROM ingredient_aliases WHERE alias_name='spring onions'"
            ).fetchone()
        )
        assert after_row == before_row, "must be left completely untouched, not self-aliased"
    finally:
        conn.close()


def test_backfill_remembered_substitutions_pair_collision(conn_factory, monkeypatch):
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO remembered_substitutions (original_name, substitute_name, "
            "created_at, updated_at) VALUES "
            "('bulgarian feta', 'greek feta', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO remembered_substitutions (original_name, substitute_name, "
            "created_at, updated_at) VALUES "
            "('bulgarian fetas', 'greek fetas', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "remembered_substitutions")
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "remembered_substitutions") == before_count
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM remembered_substitutions "
                "WHERE original_name='bulgarian feta' AND substitute_name='greek feta'"
            ).fetchone()[0]
            == 1
        )
        # Left behind, untouched (not deleted, not renamed).
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM remembered_substitutions "
                "WHERE original_name='bulgarian fetas' AND substitute_name='greek fetas'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_backfill_remembered_substitutions_self_swap_guard(conn_factory, monkeypatch):
    """A row that would normalise to original_name == substitute_name is left completely
    untouched — never silently turned into a self-swap, never deleted."""
    db_path, connect = conn_factory
    _upgrade_to(db_path, monkeypatch, _PRE_F15)

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO remembered_substitutions (original_name, substitute_name, "
            "created_at, updated_at) VALUES "
            "('spring onions', 'spring onion', datetime('now'), datetime('now'))"
        )
        conn.commit()
        before_count = _row_count(conn, "remembered_substitutions")
        before_row = dict(
            conn.execute(
                "SELECT * FROM remembered_substitutions WHERE original_name='spring onions'"
            ).fetchone()
        )
    finally:
        conn.close()

    _upgrade_to(db_path, monkeypatch, _F0_HEAD)

    conn = connect()
    try:
        assert _row_count(conn, "remembered_substitutions") == before_count
        after_row = dict(
            conn.execute(
                "SELECT * FROM remembered_substitutions WHERE original_name='spring onions'"
            ).fetchone()
        )
        assert after_row == before_row
    finally:
        conn.close()

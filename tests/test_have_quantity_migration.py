"""Migration test for a1b2c3d4e5f6 (session_checklist_items.have_quantity / have_unit).

CLAUDE.md non-negotiable rule 3: an existing checklist row must come through the upgrade
byte-identical, with the two new columns NULL ("nothing recorded").
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app import config as app_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRE = "c7c1ecd37ec8"
_HEAD = "a1b2c3d4e5f6"


def _upgrade(db_path, monkeypatch, revision):
    monkeypatch.setattr(app_config.settings, "database_path", str(db_path))
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, revision)


def test_existing_checklist_rows_survive_with_null_have_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "have_qty.db"
    _upgrade(db_path, monkeypatch, _PRE)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO planning_sessions (id, status, created_at, updated_at) "
        "VALUES (1, 'active', datetime('now'), datetime('now'))"
    )
    conn.execute(
        "INSERT INTO session_checklist_items (session_id, ingredient_name, total_quantity, "
        "total_unit, is_staple, already_on_anylist, have_it, add_to_list, needs_review, "
        "review_resolved_by_user, created_at, updated_at) "
        "VALUES (1, 'tomato', 3, NULL, 0, 0, 'no', 1, 0, 0, datetime('now'), datetime('now'))"
    )
    conn.commit()
    before = dict(conn.execute("SELECT * FROM session_checklist_items").fetchone())
    conn.close()

    _upgrade(db_path, monkeypatch, _HEAD)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM session_checklist_items").fetchall()
    conn.close()
    assert len(rows) == 1
    after = dict(rows[0])
    assert after.pop("have_quantity") is None and after.pop("have_unit") is None
    assert after == before

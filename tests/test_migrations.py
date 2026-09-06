"""Guard: the Alembic migration chain must build exactly the schema the ORM models
describe. Bootstrapped Phase 3 Chunk 3.7a — see CLAUDE.md > Code Architecture &
Maintainability > Migrations.

``Base.metadata.create_all()`` stays the fresh-DB fast path on startup, so it and
``alembic upgrade head`` must never diverge. If this test fails after a new migration,
the migration has drifted from ``app/models/`` — fix the migration, not this test.

Comparison is semantic (PRAGMA table_info / foreign_key_list / index_list), not raw
``CREATE TABLE`` text — SQLite renders constraint clauses in a different order for a batch
migration vs. ``create_all()``, which is cosmetic and not a real schema difference.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import config as app_config
from app.database import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _semantic_schema(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
            )
        ]
        schema: dict = {}
        for table in tables:
            columns = sorted(
                (r["name"], r["type"], r["notnull"], r["pk"], r["dflt_value"])
                for r in conn.execute(f"PRAGMA table_info('{table}')")
            )
            foreign_keys = sorted(
                (r["table"], r["from"], r["to"], r["on_delete"])
                for r in conn.execute(f"PRAGMA foreign_key_list('{table}')")
            )
            indexes = []
            for r in conn.execute(f"PRAGMA index_list('{table}')"):
                members = tuple(
                    ir["name"] for ir in conn.execute(f"PRAGMA index_info('{r['name']}')")
                )
                indexes.append((members, bool(r["unique"])))
            schema[table] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
                "indexes": sorted(indexes),
            }
        return schema
    finally:
        conn.close()


def test_migration_chain_matches_create_all(tmp_path, monkeypatch):
    migrated_db = tmp_path / "migrated.db"
    created_db = tmp_path / "created.db"

    # alembic/env.py derives the URL from settings.database_path at run time.
    monkeypatch.setattr(app_config.settings, "database_path", str(migrated_db))

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False  # don't disturb pytest's log capture
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{created_db}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    assert _semantic_schema(str(migrated_db)) == _semantic_schema(str(created_db))

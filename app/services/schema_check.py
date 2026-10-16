"""Is the database's schema at the revision the code expects? (2026-10-07 logging audit)

``update.bat`` migrates before restarting, but nothing stops the server being started against an
older schema (``start.bat`` without ``update.bat``, a failed migration, a restored older backup).
The symptom is then a scatter of ``OperationalError: no such column`` 500s with nothing at startup
saying why. This compares the ``alembic_version`` table with the migration head once at startup and
says so plainly. It never raises and never blocks startup: it is a diagnostic, not a blocker.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _code_heads() -> list[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return list(ScriptDirectory.from_config(Config(str(BASE_DIR / "alembic.ini"))).get_heads())


def _db_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        has_table = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        ).first()
        if not has_table:
            return None
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        return row[0] if row else None


def check_schema_revision(engine: Engine) -> str:
    """Log and return one of ``current`` | ``behind`` | ``unstamped`` | ``unknown``."""
    try:
        heads = _code_heads()
        current = _db_revision(engine)
    except Exception:  # noqa: BLE001 — a diagnostic must never take startup down
        logger.warning("Schema check: could not determine the database revision", exc_info=True)
        return "unknown"

    if current is None:
        # A database built fresh by create_all() (dev, tests) has no alembic stamp: expected.
        logger.info("Schema check: database has no alembic_version stamp (fresh create_all database)")
        return "unstamped"
    if current in heads:
        logger.info("Schema check: database schema is at the current revision (%s)", current)
        return "current"
    logger.warning(
        "Schema check: database is at revision %s but this code expects %s. Run update.bat "
        "(or `python -m alembic upgrade head`) — until then expect 'no such column/table' errors.",
        current, ", ".join(heads) or "?",
    )
    return "behind"

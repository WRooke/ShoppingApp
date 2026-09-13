"""SQLAlchemy engine, session factory, and declarative base.

Phase 1 creates all tables directly with ``Base.metadata.create_all``.
Alembic migrations take over from Phase 2 onward (see CLAUDE.md).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Timezone-aware UTC now — used as the default for all timestamp columns."""
    return datetime.now(timezone.utc)


os.makedirs(os.path.dirname(settings.database_path), exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):  # noqa: ANN001
    """SQLite ignores FOREIGN KEY constraints unless asked per-connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # 2026-09-13 code review — WAL (write-ahead log) mode instead of the default rollback-
    # journal: (a) readers no longer block behind a writer (or vice versa), which matters once
    # more than one household member's phone can be editing a checklist at the same time, and
    # (b) it materially de-risks scripts/backup.py's online-backup-API copy (see that module's
    # own docstring) against catching the database mid-write — a plain rollback-journal file
    # copy has a narrow but real window where a concurrent commit could be caught half-done;
    # WAL keeps all in-flight changes in a separate -wal file the main .db file is never
    # touched by until a checkpoint, and the sqlite3 backup API used in backup.py folds WAL
    # content in correctly regardless of journal mode. Sets a -wal/-shm file pair alongside
    # mealplanner.db; both live in the already-gitignored data/ directory. See CLAUDE.md >
    # Backup & Restore and docs/deployment-and-operations.md.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create every table that does not yet exist."""
    # Importing the models package registers all ORM classes on Base.metadata.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database ready at %s", settings.database_path)

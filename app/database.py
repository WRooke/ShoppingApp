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

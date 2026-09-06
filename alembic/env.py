"""Alembic environment — wired to the app's own SQLAlchemy metadata and .env config.

Bootstrapped at Phase 3 Chunk 3.7 (see CLAUDE.md > Code Architecture & Maintainability >
Migrations). Alembic was never actually set up in Phase 2: the app still runs
``Base.metadata.create_all()`` on startup, and every schema change up to Chunk 3.5 only
*added whole tables*, which ``create_all()`` handles. Adding columns to the existing
``recipes`` table in Chunk 3.7 is the first change that genuinely needs a migration, so
Alembic is bootstrapped here. ``create_all()`` stays as the fresh-empty-DB fast path;
schema *changes* from Chunk 3.7 onward go through Alembic.

Two deliberate choices:
  * The database URL is NOT stored in alembic.ini — it's derived from the same
    ``app.config.settings.database_path`` the running app uses, so ``alembic`` and the app
    can never point at different databases.
  * ``target_metadata`` is ``app.database.Base.metadata``, populated by importing
    ``app.models`` (which registers every table), so ``--autogenerate`` sees the real schema.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  — importing registers every table on Base.metadata
from app.config import settings
from app.database import Base

config = context.config

# The app owns the DB location (.env DATABASE_PATH, resolved to an absolute path in
# app.config). Feed it to Alembic here instead of hardcoding a URL in alembic.ini.
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.database_path}")

# Skippable via config.attributes["configure_logger"] = False so a programmatic
# command.upgrade() (e.g. tests/test_migrations.py) doesn't reconfigure the root logger
# out from under pytest's log capture — standard Alembic + pytest pattern.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite has no native ALTER for most changes — use batch copy
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite: emit ALTERs via batch table-copy
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

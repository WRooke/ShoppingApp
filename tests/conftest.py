"""Shared pytest fixtures.

Points the app at a temp SQLite file and a temp log directory *before*
``app.config`` is imported anywhere in the test session, so running the test
suite never touches the real dev database at ``data/mealplanner.db`` or the
real ``logs/app.log`` — see CLAUDE.md > Code Architecture & Maintainability.

``python-dotenv``'s ``load_dotenv`` (called at import time in app.config)
does not override an already-set environment variable by default, so setting
these here first is enough to redirect them.

**This only works if nothing has already set these three vars in THIS process's
environment before pytest starts.** If a wrapper script (e.g. something under
``scripts/``) runs pytest as a subprocess via ``subprocess.run`` and itself imports
``app.config`` (directly, or via ``app.log_config``) at module scope *before* spawning
that subprocess, ``load_dotenv()`` will already have set these three vars from ``.env``
in the wrapper's own environment — which the subprocess inherits by default, making the
``setdefault`` calls below no-ops. The suite then runs silently against the real
``data/mealplanner.db`` instead of the temp DB below, with no error, just confusing
failures (this bit ``scripts/validate_develop.py`` this way once — see DEPLOY.md >
Things that can go wrong). Any script that shells out to pytest should avoid importing
``app.config``/``app.log_config`` at all; plain ``logging.basicConfig()`` is enough for
a script's own status messages.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_TMP = Path(tempfile.mkdtemp(prefix="shoppingapp_test_"))
os.environ.setdefault("DATABASE_PATH", str(_TEST_TMP / "test.db"))
os.environ.setdefault("LOGS_PATH", str(_TEST_TMP / "logs"))
os.environ.setdefault("IMAGES_PATH", str(_TEST_TMP / "images"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as database  # noqa: E402
import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A TestClient against the real app (routes + error handlers + lifespan), on its OWN
    fresh SQLite file for this one test — not the single on-disk file the whole session used
    to share.

    2026-09-13 code review — every router test used to run against one on-disk DB shared for
    the whole pytest session (only reset once, at collection, by the fresh `_TEST_TMP` dir
    above), a known fragility: nothing stopped one test's leftover rows from silently
    propagating into another's assertions, and nothing would have caught it if it had.
    Repointing ``app.database.engine``/``SessionLocal`` at a brand-new ``tmp_path`` file per
    test (torn down with the test automatically) makes each router test as isolated as the
    services-layer tests already are (each with their own `sqlite:///:memory:` engine).

    Two module references need patching, not one: ``app.main`` did
    ``from app.database import SessionLocal`` at import time, which bound its own separate
    name in ``app.main``'s namespace — patching only ``app.database.SessionLocal`` would
    leave the lifespan's own ``seed_reference_data()`` call (and the capture-queue poller)
    still reading/writing the OLD shared database. ``app.database.get_db()`` (what every
    router's ``Depends(get_db)`` actually calls) is unaffected by that duplicate-import
    problem — it looks up ``SessionLocal`` in its own module's globals at call time, so
    patching ``app.database.SessionLocal`` alone is enough for it.

    The connect-time PRAGMAs (foreign key enforcement, WAL) are SQLAlchemy event listeners
    registered against the specific ``Engine`` object in ``app/database.py`` — they don't
    carry over to a different ``Engine`` automatically, so this re-registers the same two
    pragmas on the new one to keep test behaviour matching production (in particular, FK
    enforcement matters for any test that depends on cascade/ON DELETE behaviour).
    """
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'router_test.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    test_session_local = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, future=True
    )

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_local)
    monkeypatch.setattr(main_module, "SessionLocal", test_session_local)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        test_engine.dispose()

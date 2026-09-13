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

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """A TestClient against the real app (routes + error handlers + lifespan).

    Entering the context manager runs the app's lifespan, which calls
    ``init_db()`` — so tables exist for any test that needs them.
    """
    with TestClient(app) as test_client:
        yield test_client

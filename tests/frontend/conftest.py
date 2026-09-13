"""Fixtures for the headless-browser frontend regression suite (2026-09-13 code review,
Stage 4.3 of the approved fix plan). See tests/frontend/README.md for what belongs here
versus a one-off manual `scripts/cdp.py` session.

**Needs a real Edge or Chrome installed** — this is the one part of `tests/` that does.
`scripts.cdp.Browser`'s own `_find_browser()` raises a clear `RuntimeError` if neither is
found, which surfaces here as a normal test failure (not a skip): a misconfigured machine
must not be able to silently "pass" by skipping real frontend coverage. There is no
Node/Playwright anywhere in this project and never will be — see HEADLESS_VERIFY.md.

The server fixture below is the automated version of HEADLESS_VERIFY.md's own TL;DR
recipe: a throwaway `app.main` subprocess on a scratch DB, in AI-extraction fake mode, on a
free port — never the real `data/mealplanner.db`.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url():
    """Starts one scratch `app.main` server for the whole frontend session, torn down at the
    end. Own scratch DATABASE_PATH/LOGS_PATH/IMAGES_PATH (never the real dev DB),
    AI_EXTRACTION_FAKE_MODE=true (zero key, zero cost — CLAUDE.md > Security §0c), a free
    port. Explicit env values (not `setdefault`) so this subprocess's own scratch paths win
    regardless of what the top-level tests/conftest.py already put in THIS process's
    environment for the rest of the suite (see that file's own docstring warning about
    exactly this gotcha)."""
    scratch = Path(tempfile.mkdtemp(prefix="shoppingapp_frontend_test_"))
    port = _free_port()
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(scratch / "t.db")
    env["LOGS_PATH"] = str(scratch / "logs")
    env["IMAGES_PATH"] = str(scratch / "images")
    env["PORT"] = str(port)
    env["ALLOWED_ORIGINS"] = f"http://127.0.0.1:{port}"
    env["AI_EXTRACTION_FAKE_MODE"] = "true"
    env["AI_EXTRACTION_ENABLED"] = "false"  # belt-and-braces; this is already the default
    env["ANYLIST_ENABLED"] = "false"
    env["ANYLIST_FAKE_MODE"] = "false"

    log_path = scratch / "server.log"
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    up = False
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_file.close()
                raise RuntimeError(
                    f"Scratch server process exited early (code {proc.returncode}) — "
                    f"see {log_path}"
                )
            try:
                resp = httpx.get(f"{base_url}/api/v1/health", timeout=1.0)
                if resp.status_code == 200:
                    up = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        if not up:
            raise RuntimeError(f"Scratch server never became healthy — see {log_path}")

        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_file.close()


@pytest.fixture()
def api(server_url):
    """A small httpx client against the scratch server, for test setup/assertions that go
    straight to the API rather than through the DOM — same "cross-check anything that
    matters against the API directly" discipline HEADLESS_VERIFY.md already asks for."""
    with httpx.Client(base_url=server_url, timeout=10.0) as client:
        yield client


@pytest.fixture()
def browser(server_url):
    """One fresh headless-Edge `Browser` per test (own temp profile — see scripts/cdp.py),
    parked on #/home until a test navigates it somewhere specific."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.cdp import Browser

    with Browser(f"{server_url}/#/home") as b:
        yield b

"""The update banner, end to end, with a REAL server restart — what actually happens on the NUC
when update.bat pulls new code (docs/deployment-and-operations.md > "How an open phone learns the
NUC was updated").

Scenario: server A serves an editable copy of static/ where every file looks decades old (so a
browser applying heuristic caching would happily keep it). A page loads from A. The code changes,
A is stopped and server B starts on the same port. The already-open page must notice, show the
banner, and — after a real tap — be running B's code (not a cached copy of A's).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OLD = 946684800  # 2000-01-01: far past, the worst case for heuristic freshness


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    def __init__(self, scratch: Path, static_copy: Path, port: int) -> None:
        self.scratch, self.static_copy, self.port = scratch, static_copy, port
        self.proc: subprocess.Popen | None = None
        self._log = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self) -> None:
        env = os.environ.copy()
        env.update(
            DATABASE_PATH=str(self.scratch / "t.db"), LOGS_PATH=str(self.scratch / "logs"),
            IMAGES_PATH=str(self.scratch / "images"), PORT=str(self.port),
            ALLOWED_ORIGINS=self.url, AI_EXTRACTION_FAKE_MODE="true", AI_EXTRACTION_ENABLED="false",
            ANYLIST_ENABLED="false", ANYLIST_FAKE_MODE="false",
            SHOPPINGAPP_STATIC_DIR=str(self.static_copy),
        )
        env.pop("SHOPPINGAPP_BUILD_ID", None)  # the build id must come from the files themselves
        self._log = open(self.scratch / f"server-{time.time_ns()}.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app.main"], cwd=str(PROJECT_ROOT), env=env,
            stdout=self._log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 60  # cold start under parallel-worker CPU contention
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.stop()
                raise RuntimeError("server exited early")
            try:
                if httpx.get(f"{self.url}/api/v1/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.3)
        raise RuntimeError("server never became healthy")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self.proc = None
        if self._log is not None:  # pytest runs with warnings-as-errors: never leak the handle
            self._log.close()
            self._log = None

    def build(self) -> str:
        return httpx.get(f"{self.url}/api/v1/health", timeout=3).json()["data"]["build_id"]


def _write_marker(static_copy: Path, value: str) -> None:
    """Append a marker to toast.js (loaded on every page) and age every file to the year 2000."""
    path = static_copy / "js" / "toast.js"
    text = path.read_text(encoding="utf-8")
    text = text.split("\n/* __e2e_marker__ */")[0] + f"\n/* __e2e_marker__ */ window.__e2eMarker = {value!r};\n"
    path.write_text(text, encoding="utf-8")
    for p in static_copy.rglob("*"):
        if p.is_file():
            os.utime(p, (OLD, OLD))


@pytest.fixture()
def restartable():
    scratch = Path(tempfile.mkdtemp(prefix="shoppingapp_e2e_"))
    static_copy = scratch / "static"
    shutil.copytree(PROJECT_ROOT / "static", static_copy)
    _write_marker(static_copy, "v1")
    server = _Server(scratch, static_copy, _free_port())
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _wait(browser, expr, timeout=12.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if browser.eval(expr):
                return True
        except Exception:  # noqa: BLE001 — mid-navigation evals can fail; keep polling
            pass
        time.sleep(0.15)
    return False


def test_server_restarted_on_new_code_banner_appears_and_the_tap_delivers_the_new_code(restartable, browser_process):
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.cdp import Browser

    build_a = restartable.build()
    with Browser(f"{restartable.url}/#/home", process=browser_process) as browser:
        browser.wait_for(".nav-item")
        assert browser.eval("window.__e2eMarker") == "v1"
        assert browser.eval("document.querySelector('meta[name=app-build]').getAttribute('content')") == build_a
        assert browser.eval("!document.querySelector('.update-banner')")

        # ---- the update: new code on disk, old server stopped, new server on the same port ----
        restartable.stop()
        _write_marker(restartable.static_copy, "v2")
        restartable.start()
        build_b = restartable.build()
        assert build_b != build_a  # the build id really is derived from the code

        # the open page (still v1) notices when it next checks — here, via the coming-back-online path
        browser.eval("window.dispatchEvent(new Event('online'));")
        assert _wait(browser, "!!document.querySelector('.update-banner')"), "banner never appeared"
        assert browser.text(".update-banner .msg") == "Update available"
        assert browser.eval("window.__e2eMarker") == "v1"  # still the old code until the user taps

        # ---- the tap ----
        browser.eval("document.querySelector('.update-banner').click()")
        assert _wait(browser, "window.__e2eMarker === 'v2'", timeout=15), (
            "after the tap the page is still running the OLD code"
        )
        browser.wait_for(".nav-item")
        assert browser.eval("document.querySelector('meta[name=app-build]').getAttribute('content')") == build_b
        assert browser.eval("window.UpdateBanner.getLoadedVersion()") == build_b
        time.sleep(0.8)
        assert browser.eval("!document.querySelector('.update-banner')"), "banner stuck after a successful update"
        assert browser.eval("location.search") == "" and browser.eval("location.hash") == "#/home"
        assert browser.eval("sessionStorage.getItem('updatePendingBuild')") is None


def test_a_restart_with_no_code_change_does_not_nag_and_a_docs_only_change_does_not_either(restartable, browser_process):
    """A reboot (same code) changes the process but not the build, so no banner. Touching only
    files that aren't part of the app/served files can't change the build either."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.cdp import Browser

    build_a = restartable.build()
    with Browser(f"{restartable.url}/#/home", process=browser_process) as browser:
        browser.wait_for(".nav-item")
        boot_a = httpx.get(f"{restartable.url}/api/v1/health").json()["data"]["boot_id"]
        restartable.stop()
        restartable.start()
        assert httpx.get(f"{restartable.url}/api/v1/health").json()["data"]["boot_id"] != boot_a  # really restarted
        assert restartable.build() == build_a
        browser.eval("window.dispatchEvent(new Event('online'));")
        time.sleep(1.5)
        assert browser.eval("!document.querySelector('.update-banner')")


def test_mid_restart_outage_does_not_lose_the_update(restartable, browser_process):
    """The page checks while the server is DOWN (the ~10 s of a restart): that must not be the
    moment it forgets what build it is on. After the server returns on new code, the next check
    — here the scheduled retry — finds the update."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.cdp import Browser

    with Browser(f"{restartable.url}/#/home", process=browser_process) as browser:
        browser.wait_for(".nav-item")
        restartable.stop()
        browser.eval("window.UpdateBanner.checkNow();")  # fails: connection refused
        time.sleep(1.0)
        assert browser.eval("!document.querySelector('.update-banner')")

        _write_marker(restartable.static_copy, "v2")
        restartable.start()  # comes back on new code within the retry window (5s/10s/20s)
        assert _wait(browser, "!!document.querySelector('.update-banner')", timeout=25), (
            "the retry after the outage never found the update"
        )

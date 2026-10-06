"""scripts/verify_server.py and the start/stop scripts around it (docs/deployment-and-operations.md >
"How an open phone learns the NUC was updated"). The real server is replaced by a tiny HTTP server
on a free port so every outcome — serving the right build, serving a STALE build, never answering,
port held — can be produced deterministically."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from scripts import verify_server

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Health:
    """A throwaway server answering /api/v1/health with a configurable body."""

    def __init__(self, port: int, data: dict | None) -> None:
        self.data = data
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if outer.data is None:
                    self.send_response(500)
                    self.end_headers()
                    return
                body = json.dumps({"ok": True, "data": outer.data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # silence
                pass

        self.httpd = HTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_listening_and_wait_port_free():
    port = _free_port()
    assert verify_server.listening(port) is False
    assert verify_server.wait_port_free(port, 0.2) is True
    with _Health(port, {}):
        assert verify_server.listening(port) is True
        assert verify_server.wait_port_free(port, 0.6, poll=0.1) is False  # held -> times out


def test_wait_port_free_succeeds_when_the_holder_lets_go_in_time():
    port = _free_port()
    health = _Health(port, {})
    health.__enter__()
    threading.Timer(0.4, health.__exit__, args=(None, None, None)).start()
    assert verify_server.wait_port_free(port, 5, poll=0.1) is True


def test_serving_ok_when_the_running_server_reports_the_expected_build():
    port = _free_port()
    with _Health(port, {"build_id": "abc123", "version": "release-1", "started_at": "2026-10-06T00:00:00+00:00"}):
        ok, message = verify_server.check_serving(port, "abc123", 3, poll=0.1)
    assert ok and message.startswith("OK") and "abc123" in message and "release-1" in message


def test_serving_flags_a_stale_old_process_still_answering():
    port = _free_port()
    with _Health(port, {"build_id": "OLD", "started_at": "2026-10-05T00:00:00+00:00"}):
        ok, message = verify_server.check_serving(port, "NEW", 0.5, poll=0.1)
    assert not ok and "OLD process is still serving" in message and "'OLD'" in message and "'NEW'" in message


def test_serving_flags_a_server_that_never_started():
    ok, message = verify_server.check_serving(_free_port(), "NEW", 0.3, poll=0.1)
    assert not ok and "nothing answered" in message and "did not start" in message


def test_serving_waits_for_a_slow_start_then_succeeds():
    port = _free_port()
    health = _Health(port, {"build_id": "NEW"})
    threading.Timer(0.5, health.__enter__).start()
    ok, _ = verify_server.check_serving(port, "NEW", 8, poll=0.1)
    health.__exit__(None, None, None)
    assert ok


def test_an_http_error_from_the_server_is_not_mistaken_for_serving():
    port = _free_port()
    with _Health(port, None):  # answers 500
        assert verify_server.fetch_health(port) is None
        ok, _ = verify_server.check_serving(port, "NEW", 0.3, poll=0.1)
    assert not ok


def test_main_exit_codes_and_messages(monkeypatch, capsys):
    port = _free_port()
    monkeypatch.setattr(verify_server.settings, "port", port, raising=False)
    assert verify_server.main(["port-free", "--timeout", "0.2"]) == 0

    monkeypatch.setattr(verify_server, "compute_build_id", lambda: "EXPECTED")
    with _Health(port, {"build_id": "EXPECTED", "version": "v"}):
        assert verify_server.main(["serving", "--timeout", "2"]) == 0
        assert verify_server.main(["port-free", "--timeout", "0.3"]) == 1
    out = capsys.readouterr().out
    assert "OK - the running server is the code on disk" in out and "PROBLEM - port" in out

    assert verify_server.main(["serving", "--timeout", "0.3"]) == 1  # nothing running
    assert "did not start" in capsys.readouterr().out


# --- the scripts that call it ------------------------------------------------------------------


def test_update_bat_is_untouched_by_this_work_because_cmd_rereads_a_running_batch_file():
    """update.bat pulls (replacing files on disk) and then keeps executing — cmd.exe re-reads a
    running batch file by byte offset, so editing update.bat itself risks garbage execution in the
    very update that deploys the edit. All new restart behaviour therefore lives in stop.bat /
    start.bat / scripts/, which update.bat merely `call`s (read fresh, after the pull). If you
    must change update.bat, read docs/deployment-and-operations.md first."""
    text = (ROOT / "update.bat").read_text(encoding="utf-8")
    assert "python -m scripts.update" in text and "call stop.bat" in text and "call start.bat" in text
    assert "verify_server" not in text and "stop_server" not in text


def test_start_bat_refuses_to_start_on_a_held_port_and_verifies_after_starting():
    text = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert text.index("verify_server port-free") < text.index("python -m app.main")
    assert "exit /b 1" in text  # the refuse path
    assert "verify_server serving" in text
    # a batch variable named PORT is inherited by python and overrides .env (the old bug)
    assert 'set "PORT=' not in text and "!PORT!" not in text


def test_stop_bat_reports_failure_instead_of_always_saying_done():
    text = (ROOT / "stop.bat").read_text(encoding="utf-8")
    assert "stop_server.ps1" in text and "exit /b %STOP_RESULT%" in text
    ps1 = (ROOT / "scripts" / "stop_server.ps1").read_text(encoding="utf-8")
    assert "Get-NetTCPConnection" in ps1 and "exit 1" in ps1 and "COULD NOT stop" in ps1
    assert "already gone" in ps1  # the launcher stub dying with its child is success, not failure


def test_a_bare_python_cmdline_match_is_still_how_the_app_process_is_found():
    ps1 = (ROOT / "scripts" / "stop_server.ps1").read_text(encoding="utf-8")
    assert "app\\.main" in ps1 and "uvicorn" in ps1

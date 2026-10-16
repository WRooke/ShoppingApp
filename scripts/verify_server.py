"""Post-restart checks for the NUC's start/stop scripts (docs/deployment-and-operations.md >
"How an open phone learns the NUC was updated").

Two subcommands, both exit 0 on success / 1 on failure and print a plain-language result (also
logged to app.log so it can be found later):

  python -m scripts.verify_server port-free [--timeout 15]
      Wait until nothing is listening on the app's port. start.bat runs it before launching so
      that a server that stop.bat failed to kill produces a clear message instead of the new
      process silently dying on "address already in use" while the OLD (stale) code keeps
      serving — one of the reasons the in-app "new version available" banner never fired on phones
      (the banner works by comparing ``build_id`` — a hash of the code files on disk — with the
      one the running server reported at startup via /api/v1/health).

  python -m scripts.verify_server serving [--timeout 90]
      Poll the freshly started server's GET /api/v1/health until it answers, then compare the
      ``build_id`` it reports with the id computed here, from the files on disk. Equal = the
      running server is the code that was just pulled. Different = an OLD process is still
      serving (or the pull didn't land). Never answers = the server didn't start.

Deliberately imports nothing heavy (no FastAPI app) and no git: it must work in the same bare
environment the server itself is started in.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import time
import urllib.error
import urllib.request

from app.config import settings
from app.log_config import setup_logging
from app.services.version import compute_build_id

setup_logging(rotate=False)  # the server alone rotates app.log
logger = logging.getLogger(__name__)


def _say(level: int, message: str) -> None:
    logger.log(level, "Verify: %s", message)
    print(message, flush=True)


def listening(port: int, host: str = "127.0.0.1") -> bool:
    """True if something accepts a TCP connection on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def wait_port_free(port: int, timeout: float, *, poll: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if not listening(port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def fetch_health(port: int, host: str = "127.0.0.1", timeout: float = 3.0) -> dict | None:
    """The ``data`` object of /api/v1/health, or None if the server is not (yet) answering."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/v1/health", timeout=timeout) as resp:
            return json.load(resp).get("data") or {}
    except urllib.error.HTTPError as exc:
        exc.close()  # an error response owns an open socket; don't leak it
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check_serving(port: int, expected_build: str, timeout: float, *, poll: float = 1.0) -> tuple[bool, str]:
    """(ok, message). Polls until the server reports ``expected_build`` or ``timeout`` passes."""
    deadline = time.monotonic() + timeout
    last_other: dict | None = None
    while True:
        data = fetch_health(port)
        if data is not None:
            if data.get("build_id") == expected_build:
                return True, (
                    f"OK - the running server is the code on disk (build {expected_build}, "
                    f"{data.get('version', 'unknown')}, started {data.get('started_at', '?')}). "
                    "Phones that already have the app open will show 'Update available'."
                )
            last_other = data
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)
    if last_other is not None:
        return False, (
            f"PROBLEM - a server is answering on port {port}, but it reports build "
            f"{last_other.get('build_id')!r} (started {last_other.get('started_at', '?')}), not the "
            f"{expected_build!r} that is on disk. The OLD process is still serving (stop.bat did not "
            "stop it) or the new code did not load. Phones will keep running old code until this is "
            "fixed: close every ShoppingApp window, end any python.exe running app.main in Task "
            "Manager, then run start.bat."
        )
    return False, (
        f"PROBLEM - nothing answered on port {port} within {int(timeout)}s. The server did not "
        "start; read the window it is running in (and logs/app.log) for the reason."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_free = sub.add_parser("port-free")
    p_free.add_argument("--timeout", type=float, default=15.0)
    p_serve = sub.add_parser("serving")
    p_serve.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)
    port = settings.port

    if args.cmd == "port-free":
        if wait_port_free(port, args.timeout):
            return 0
        _say(
            logging.ERROR,
            f"PROBLEM - port {port} is still in use after {int(args.timeout)}s, so a new server "
            "cannot start. An old ShoppingApp process was not stopped. End any python.exe running "
            "app.main in Task Manager (or reboot), then run start.bat again.",
        )
        return 1

    ok, message = check_serving(port, compute_build_id(), args.timeout)
    _say(logging.INFO if ok else logging.ERROR, message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

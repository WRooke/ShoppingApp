"""App version identifier — for the client auto-update banner (see CLAUDE.md > UI/UX >
Client auto-update notification, and > Deployment & Operations).

`scripts/deploy.py` tags each release `release-<timestamp>` and `scripts/update.py` already
logs `git describe --tags --always` after pulling one on the NUC — this reuses that exact
git invocation so the version string reported here matches what an operator sees at deploy
time. Computed once at process startup and cached (a `git` subprocess on every request would
be wasteful and pointless — the value can't change while this process is running), with a
plain `"dev"` fallback when `git` isn't available at all (e.g. a non-git deployment).
"""

from __future__ import annotations

import logging
import subprocess

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

_cached_version: str | None = None


def get_version() -> str:
    """The running process's version string, computed once and cached thereafter."""
    global _cached_version
    if _cached_version is not None:
        return _cached_version

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        version = result.stdout.strip()
        _cached_version = version or "dev"
    except Exception:  # noqa: BLE001 — no git, no repo, no commits yet: fall back, don't crash
        logger.warning("version.get_version: couldn't determine git version, falling back to 'dev'", exc_info=True)
        _cached_version = "dev"

    return _cached_version

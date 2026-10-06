"""Which build of the app is running — the identity the client auto-update banner compares.

See docs/deployment-and-operations.md > "How an open phone learns the NUC was updated" and
docs/ui-ux.md > Client auto-update notification. The short version: the page remembers the build
id of the assets it was *served* (a ``<meta name="app-build">`` the server writes into
``index.html``), and checks it against ``GET /api/v1/health`` — if they differ, the NUC has been
updated since this page loaded, so show "Update available".

**The build id is a hash of the code itself** (every file under ``app/`` and ``static/``), not a
git command. Until 2026-10-06 it was ``git describe --tags --always`` run once in the server
process with a constant ``"dev"`` fallback — which meant that if ``git`` was not on the PATH of
whatever launched the server (Task Scheduler runs it unelevated, in a different environment from
an interactive ``update.bat``), or git refused the directory ("dubious ownership"), every build
reported ``"dev"`` forever and the banner could never fire. A content hash needs no git, cannot
fail silently, and changes exactly when the code the browser would load (or the server runs)
changes. The git description is kept only as a human-readable *label* (best effort, never
compared).

Computed once per process and cached: the files cannot change under a running server in any way
that matters (an update replaces them and restarts the process).
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

# What goes into the hash: the Python the server runs and everything the browser is served.
_HASHED_DIRS = ("app", "static")
_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}

# Test hooks: pin the id (the update banner's end-to-end test restarts a server "as" a new build)
# and point the hash at an editable copy of the static files.
ENV_BUILD_ID = "SHOPPINGAPP_BUILD_ID"
ENV_STATIC_DIR = "SHOPPINGAPP_STATIC_DIR"


@dataclass(frozen=True)
class BuildInfo:
    build_id: str  # compared by the client; changes iff the code changed
    label: str  # human-readable (git describe), or "unknown" — display only, never compared
    label_source: str  # "git" | "unavailable"
    boot_id: str  # unique per server process (diagnostics: tells a restart from a no-op)
    started_at: str  # ISO-8601 UTC


def static_dir() -> Path:
    override = os.environ.get(ENV_STATIC_DIR)
    return Path(override) if override else BASE_DIR / "static"


def compute_build_id(base_dir: Path | None = None, static_override: Path | None = None) -> str:
    """Short hash over the relative path and bytes of every file under ``app/`` and ``static/``
    (sorted, so it is independent of directory-listing order). Deterministic across machines and
    across a ``git pull`` that touches only docs/tests (those are not hashed — no banner for a
    change nobody's browser or server would notice). Public so ``scripts/verify_server.py`` can
    compute what the freshly started server SHOULD report, from a separate process."""
    base = Path(base_dir) if base_dir else BASE_DIR
    digest = hashlib.sha256()
    for name in _HASHED_DIRS:
        root = (static_override if (name == "static" and static_override) else base / name)
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if _SKIP_DIRS & set(path.relative_to(root).parts) or path.suffix in _SKIP_SUFFIXES:
                continue
            digest.update(f"{name}/{path.relative_to(root).as_posix()}\0".encode())
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:12]


def _git_label() -> tuple[str, str]:
    """Best-effort ``git describe`` for humans ("release-20260930-214559Z"). Passes
    ``safe.directory`` explicitly so git's "dubious ownership" refusal (repo owned by a different
    Windows account than the server's) cannot blank it. Any failure -> ("unknown", "unavailable");
    never raises and is never compared, so a missing git costs only the label."""
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={BASE_DIR.as_posix()}", "describe", "--tags", "--always"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=5, check=True,
        )
        label = result.stdout.strip()
        if label:
            return label, "git"
    except Exception as exc:  # noqa: BLE001 — no git, no repo, no commits: label only
        logger.info("version: git label unavailable (%s: %s) — build id is unaffected", type(exc).__name__, exc)
    return "unknown", "unavailable"


_cached: BuildInfo | None = None


def get_build_info() -> BuildInfo:
    """The running process's build identity, computed once and cached."""
    global _cached
    if _cached is None:
        override = os.environ.get(ENV_BUILD_ID)
        if override:
            build_id = override.strip()
        else:
            build_id = compute_build_id(static_override=Path(os.environ[ENV_STATIC_DIR]) if os.environ.get(ENV_STATIC_DIR) else None)
        label, source = _git_label()
        _cached = BuildInfo(
            build_id=build_id,
            label=label,
            label_source=source,
            boot_id=uuid.uuid4().hex[:12],
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        logger.info(
            "Build: id=%s label=%s (%s) boot_id=%s",
            _cached.build_id, _cached.label, _cached.label_source, _cached.boot_id,
        )
    return _cached


def get_build_id() -> str:
    return get_build_info().build_id


def get_version() -> str:
    """The human-readable label (kept under its old name for existing callers/tests)."""
    return get_build_info().label


def reset_for_tests() -> None:
    global _cached
    _cached = None

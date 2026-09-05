"""Pull the latest deployed release and refresh dependencies on the NUC.

Run via update.bat, which calls this FIRST and only calls stop.bat / start.bat itself if
this exits 0. That ordering means a failed update leaves the previous version running
rather than taking the app down.

Never force-merges or stashes on your behalf - if the working tree is dirty or history has
diverged (e.g. a backup commit made by scripts/backup.py hasn't reached origin yet), this
aborts with an explanation rather than guessing. See DEPLOY.md.

Invoke as ``python -m scripts.update`` from the project root (see update.bat).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from app.log_config import setup_logging
from scripts.git_utils import run_git

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _fail(message: str) -> None:
    logger.error("Update: %s", message)
    print(f"\n{message}\n")


def main() -> int:
    is_repo, _ = run_git(BASE_DIR, "rev-parse", "--is-inside-work-tree")
    if not is_repo:
        _fail("This folder is not a git repository. See DEPLOY.md to set it up (git clone).")
        return 1

    status_ok, status_out = run_git(BASE_DIR, "status", "--porcelain")
    if not status_ok:
        _fail(f"Could not check git status: {status_out}")
        return 1
    if status_out.strip():
        _fail(
            "Working tree has uncommitted or local changes - refusing to pull over them:\n"
            f"{status_out}\n"
            "Resolve this by hand (commit, stash, or discard) on the NUC, then re-run "
            "update.bat."
        )
        return 1

    fetch_ok, fetch_out = run_git(BASE_DIR, "fetch", "origin")
    if not fetch_ok:
        _fail(f"git fetch failed: {fetch_out}")
        return 1

    branch_ok, branch_out = run_git(BASE_DIR, "symbolic-ref", "--short", "HEAD")
    branch = branch_out.strip() if branch_ok else "main"

    pull_ok, pull_out = run_git(BASE_DIR, "pull", "--ff-only", "origin", branch)
    if not pull_ok:
        _fail(
            "git pull --ff-only failed - local and origin history have diverged:\n"
            f"{pull_out}\n"
            "This needs a person to look at it on the NUC (e.g. `git log --oneline --all "
            "--graph`), not an automatic merge. Resolve, then re-run update.bat."
        )
        return 1
    logger.info("Update: %s", pull_out or "already up to date")

    logger.info("Update: installing/upgrading dependencies...")
    pip = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=BASE_DIR,
    )
    if pip.returncode != 0:
        _fail("pip install failed - see output above. Server NOT restarted.")
        return 1

    _, version = run_git(BASE_DIR, "describe", "--tags", "--always")
    logger.info("Update: now at %s", version.strip())
    print(f"\nUpdated to {version.strip()}. Restarting the server...\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

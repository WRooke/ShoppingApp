"""Pull the latest deployed release and refresh dependencies on the NUC.

Run via update.bat, which calls this FIRST and only calls stop.bat / start.bat itself if
this exits 0. That ordering means a failed update leaves the previous version running
rather than taking the app down.

Branch model (see CLAUDE.md > Deferred Decisions > Git branching strategy, decided at the
Phase 2 review): the NUC always stays checked out on `production` - the branch
scripts/deploy.py fast-forwards from the dev PC's `develop` branch. This always pulls
`production` specifically, regardless of what happens to be checked out, so a NUC checkout
that's drifted onto the wrong branch fails loudly here rather than silently pulling the
wrong thing.

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
PROD_BRANCH = "production"


def _fail(message: str) -> None:
    logger.error("Update: %s", message)
    print(f"\n{message}\n")


def main() -> int:
    is_repo, repo_out = run_git(BASE_DIR, "rev-parse", "--is-inside-work-tree")
    if not is_repo:
        _fail(
            f"Not in a usable git repository ({repo_out}). See DEPLOY.md to set it up "
            "(git clone)."
        )
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

    branch_ok, branch_out = run_git(BASE_DIR, "symbolic-ref", "--short", "HEAD")
    branch = branch_out.strip() if branch_ok else ""
    if branch != PROD_BRANCH:
        _fail(
            f"On branch '{branch or '(detached HEAD)'}', not '{PROD_BRANCH}' - the NUC "
            f"always runs {PROD_BRANCH}. If this is mid-rollback (see DEPLOY.md), finish "
            f"resuming with `git checkout {PROD_BRANCH}` first, then re-run update.bat."
        )
        return 1

    fetch_ok, fetch_out = run_git(BASE_DIR, "fetch", "origin")
    if not fetch_ok:
        _fail(f"git fetch failed: {fetch_out}")
        return 1

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

    # Apply any DB schema migrations the pulled commit added, BEFORE the restart, so the
    # new code never starts against an old schema. Alembic bootstrapped in Phase 3 Chunk
    # 3.7 (see CLAUDE.md > Code Architecture > Migrations). Nullable-column adds are the
    # common case and safe on a populated table; a migration that fails here aborts the
    # update with the old version still running, same as a failed pip install above.
    logger.info("Update: applying database migrations (alembic upgrade head)...")
    alembic_run = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BASE_DIR,
    )
    if alembic_run.returncode != 0:
        _fail("alembic upgrade head failed - see output above. Server NOT restarted.")
        return 1

    _, version = run_git(BASE_DIR, "describe", "--tags", "--always")
    logger.info("Update: now at %s", version.strip())
    print(f"\nUpdated to {version.strip()}. Restarting the server...\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

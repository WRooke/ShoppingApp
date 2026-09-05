"""Package + push a release from the dev PC (git-based deploy).

"Packaging" here just means: verify the working tree is clean and up to date with origin,
tag the commit, and push branch + tag to origin. Git itself is the transport - there is no
zip/copy step and nothing is sent directly to the NUC. Run the NUC-side counterpart
(update.bat) afterwards to actually pull it down and restart the server.

See DEPLOY.md for the one-time git/GitHub setup this depends on.

Invoke as ``python -m scripts.deploy`` from the project root (see deploy.bat).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.log_config import setup_logging
from scripts.git_utils import run_git

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _fail(message: str) -> None:
    logger.error("Deploy: %s", message)
    print(f"\n{message}\n")


def main() -> int:
    is_repo, _ = run_git(BASE_DIR, "rev-parse", "--is-inside-work-tree")
    if not is_repo:
        _fail(
            "This folder is not a git repository yet. See DEPLOY.md to set one up:\n"
            "  git init\n"
            "  git remote add origin https://github.com/<you>/<private-repo>.git"
        )
        return 1

    remote_ok, _ = run_git(BASE_DIR, "remote", "get-url", "origin")
    if not remote_ok:
        _fail(
            "No 'origin' remote configured. Add your private GitHub repo first (see "
            "DEPLOY.md):\n  git remote add origin https://github.com/<you>/<private-repo>.git"
        )
        return 1

    status_ok, status_out = run_git(BASE_DIR, "status", "--porcelain")
    if not status_ok:
        _fail(f"Could not check git status: {status_out}")
        return 1
    if status_out.strip():
        _fail(
            "You have uncommitted changes - commit them first so the NUC pulls exactly "
            "what you tested:\n" + status_out
        )
        return 1

    branch_ok, branch_out = run_git(BASE_DIR, "symbolic-ref", "--short", "HEAD")
    branch = branch_out.strip() if branch_ok else "main"

    fetch_ok, fetch_out = run_git(BASE_DIR, "fetch", "origin")
    if not fetch_ok:
        _fail(f"git fetch failed: {fetch_out}")
        return 1

    behind_ok, behind_out = run_git(BASE_DIR, "rev-list", "--count", f"HEAD..origin/{branch}")
    if behind_ok and behind_out.strip() not in ("", "0"):
        _fail(
            f"Local {branch} is {behind_out.strip()} commit(s) behind origin/{branch} - "
            f"pull before deploying (git pull --ff-only origin {branch})."
        )
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    tag = f"release-{stamp}"
    tag_ok, tag_out = run_git(BASE_DIR, "tag", "-a", tag, "-m", f"Deploy {stamp}")
    if not tag_ok:
        _fail(f"Could not create tag {tag}: {tag_out}")
        return 1

    push_ok, push_out = run_git(BASE_DIR, "push", "origin", branch)
    if not push_ok:
        run_git(BASE_DIR, "tag", "-d", tag)
        _fail(f"git push failed, tag rolled back locally: {push_out}")
        return 1

    tag_push_ok, tag_push_out = run_git(BASE_DIR, "push", "origin", tag)
    if not tag_push_ok:
        _fail(
            f"Branch pushed OK, but pushing tag {tag} failed (non-fatal, code is up to "
            f"date on origin): {tag_push_out}"
        )

    _, commit = run_git(BASE_DIR, "rev-parse", "--short", "HEAD")
    logger.info("Deploy: pushed %s (%s) to origin/%s", tag, commit.strip(), branch)
    print(f"\nPushed {tag} ({commit.strip()}) to origin/{branch}.")
    print("On the NUC: run update.bat to pull it down and restart the server.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

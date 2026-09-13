"""Validate the develop branch before pushing.

Runs tests, checks the working tree is clean, and verifies we're on the develop branch.
This is the pre-push validation gate for the develop branch on the dev PC.

Invoke as ``python -m scripts.validate_develop`` from the project root (see validate-develop.bat).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from scripts.git_utils import run_git

# Deliberately NOT `from app.log_config import setup_logging`: that import pulls in
# app.config, whose module-level `load_dotenv()` sets DATABASE_PATH/LOGS_PATH/IMAGES_PATH
# from .env into THIS PROCESS's environment. Since _run_pytest() below spawns pytest as a
# subprocess that inherits our environment, those vars would already be set by the time
# tests/conftest.py's `os.environ.setdefault(...)` runs -- setdefault is then a no-op, and
# the "isolated" test suite silently runs against the real dev database instead of a temp
# one (see conftest.py's docstring). Plain stdlib logging avoids importing app.config at
# all, so this script can never poison that subprocess's environment.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_BRANCH = "develop"


def _fail(message: str) -> None:
    logger.error("Validate: %s", message)
    print(f"\n{message}\n")


def _run_pytest() -> bool:
    """Run the test suite and return True if all tests pass."""
    logger.info("Running test suite...")
    print("\n--- Running tests ---\n")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=BASE_DIR,
            capture_output=False,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("Could not run tests: %s", e)
        return False


def main() -> int:
    print("\n=== Validate develop branch before pushing ===\n")

    # Check it's a git repo
    is_repo, repo_out = run_git(BASE_DIR, "rev-parse", "--is-inside-work-tree")
    if not is_repo:
        _fail(
            f"Not in a usable git repository ({repo_out}). Initialize with:\n"
            "  git init\n"
            "  git remote add origin https://github.com/<you>/<private-repo>.git"
        )
        return 1

    # Check origin remote is configured
    remote_ok, _ = run_git(BASE_DIR, "remote", "get-url", "origin")
    if not remote_ok:
        _fail(
            "No 'origin' remote configured. Add your GitHub repo first:\n"
            "  git remote add origin https://github.com/<you>/<private-repo>.git"
        )
        return 1

    # Check working tree is clean
    status_ok, status_out = run_git(BASE_DIR, "status", "--porcelain")
    if not status_ok:
        _fail(f"Could not check git status: {status_out}")
        return 1

    if status_out.strip():
        _fail(
            "You have uncommitted changes - commit them first:\n" + status_out
        )
        return 1

    # Check we're on the develop branch
    branch_ok, branch_out = run_git(BASE_DIR, "symbolic-ref", "--short", "HEAD")
    branch = branch_out.strip() if branch_ok else ""
    if branch != DEV_BRANCH:
        _fail(
            f"On branch '{branch or '(detached HEAD)'}', not '{DEV_BRANCH}'.\n"
            f"Run: git checkout {DEV_BRANCH}"
        )
        return 1

    print(f"OK: on {DEV_BRANCH} branch")
    print("OK: working tree is clean")
    print("OK: origin remote is configured\n")

    # Run tests
    if not _run_pytest():
        _fail("Tests failed - fix them before pushing.")
        return 1

    print("\nOK: all tests passed")
    print("\n=== Validation complete ===")
    print(f"Ready to push {DEV_BRANCH} to origin.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

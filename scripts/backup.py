"""Weekly automated backup (Schema & Planning Addendum #4).

What it does, every run:
  1. Copies the live SQLite .db file into backups/ with a timestamped name.
  2. Dumps every table to a JSON file alongside it (diffable, unlike the binary .db).
  3. Trims old backups, keeping the most recent KEEP_COUNT pairs.
  4. If the project is a git repo, commits backups/, rebases onto the latest origin
     (this same repo also receives code deploys — see DEPLOY.md), and pushes if a
     remote named "origin" is configured. Never fatal if git isn't set up yet — logs
     a warning and stops there.

Images are deliberately NOT backed up (see CLAUDE.md > Backup & Restore).

Invoke as ``python -m scripts.backup`` from the project root (see backup.bat).
Intended to be wired into Windows Task Scheduler, weekly (see SETUP.md).
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.log_config import setup_logging
from scripts.git_utils import run_git

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backups"
KEEP_COUNT = 12  # ~ a quarter of weekly backups


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def dump_db_to_json(db_path: Path) -> dict:
    """Read every table via plain sqlite3 (no ORM dependency) into a JSON-able dict."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        dump = {}
        for table in tables:
            rows = con.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - table names from sqlite_master, not user input
            dump[table] = [dict(row) for row in rows]
        return dump
    finally:
        con.close()


def commit_and_push() -> None:
    is_repo, _ = run_git(BASE_DIR, "rev-parse", "--is-inside-work-tree")
    if not is_repo:
        logger.warning("Backup: not a git repository yet - backup saved locally only.")
        return

    status_ok, status_out = run_git(BASE_DIR, "status", "--porcelain", "--", "backups")
    if not status_ok:
        logger.warning("Backup: could not check git status: %s", status_out)
        return
    if not status_out.strip():
        logger.info("Backup: no changes under backups/ to commit.")
        return

    add_ok, add_out = run_git(BASE_DIR, "add", "backups")
    if not add_ok:
        logger.error("Backup: git add failed: %s", add_out)
        return

    commit_ok, commit_out = run_git(
        BASE_DIR, "commit", "-m", f"Automated backup {_timestamp()}"
    )
    if not commit_ok:
        logger.error("Backup: git commit failed: %s", commit_out)
        return
    logger.info("Backup: committed locally.")

    remote_ok, _ = run_git(BASE_DIR, "remote", "get-url", "origin")
    if not remote_ok:
        logger.warning("Backup: no 'origin' remote configured yet - commit created locally only.")
        return

    # This repo/branch also receives code pushes from the dev PC (see deploy.bat /
    # update.bat and DEPLOY.md). Rebase the backup commit onto the latest origin state
    # first, so an out-of-date NUC checkout doesn't turn every backup into a failed,
    # un-pushed push that then piles up.
    fetch_ok, fetch_out = run_git(BASE_DIR, "fetch", "origin")
    if not fetch_ok:
        logger.warning("Backup: git fetch failed, will still try to push as-is: %s", fetch_out)
    else:
        branch_ok, branch_out = run_git(BASE_DIR, "symbolic-ref", "--short", "HEAD")
        branch = branch_out.strip() if branch_ok else "main"
        rebase_ok, rebase_out = run_git(BASE_DIR, "rebase", f"origin/{branch}")
        if not rebase_ok:
            run_git(BASE_DIR, "rebase", "--abort")
            logger.error(
                "Backup: rebase onto origin/%s failed (likely a real conflict) - backup "
                "commit kept locally, unpushed. Resolve manually: %s",
                branch,
                rebase_out,
            )
            return

    push_ok, push_out = run_git(BASE_DIR, "push", "origin", "HEAD")
    if push_ok:
        logger.info("Backup: pushed to origin.")
    else:
        logger.error("Backup: git push failed: %s", push_out)


def trim_old_backups() -> None:
    db_backups = sorted(BACKUP_DIR.glob("mealplanner_*.db"))
    if len(db_backups) <= KEEP_COUNT:
        return
    for old_db in db_backups[: len(db_backups) - KEEP_COUNT]:
        old_json = old_db.with_suffix(".json")
        old_db.unlink(missing_ok=True)
        old_json.unlink(missing_ok=True)
        logger.info("Backup: trimmed old backup %s", old_db.name)


def run_backup() -> Path:
    db_path = Path(settings.database_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path} - nothing to back up.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    dest_db = BACKUP_DIR / f"mealplanner_{stamp}.db"
    dest_json = BACKUP_DIR / f"mealplanner_{stamp}.json"

    logger.info("Backup: starting (source=%s)", db_path)
    shutil.copy2(db_path, dest_db)

    dump = dump_db_to_json(db_path)
    dest_json.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")

    row_counts = {k: len(v) for k, v in dump.items()}
    logger.info("Backup: wrote %s and %s (rows: %s)", dest_db.name, dest_json.name, row_counts)

    trim_old_backups()
    commit_and_push()

    logger.info("Backup: complete.")
    return dest_db


if __name__ == "__main__":
    try:
        run_backup()
    except Exception:
        logger.error("Backup: failed", exc_info=True)
        raise

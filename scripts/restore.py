"""Restore the database from a backup made by scripts/backup.py.

Usage (from the project root, see restore.bat):
    python -m scripts.restore                  list available backups, do nothing
    python -m scripts.restore latest            dry run: show what restoring "latest" would do
    python -m scripts.restore latest --yes      actually restore the most recent backup
    python -m scripts.restore 20260904-073600Z --yes   restore a specific backup by timestamp

Never overwrites without --yes. Always saves a pre-restore copy of the current
database first, so a restore can itself be undone.
"""

from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.log_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backups"


def list_backups() -> list[Path]:
    return sorted(BACKUP_DIR.glob("mealplanner_*.db"))


def resolve_target(identifier: str) -> Path:
    backups = list_backups()
    if not backups:
        raise FileNotFoundError(f"No backups found in {BACKUP_DIR}")

    if identifier == "latest":
        return backups[-1]

    candidate = BACKUP_DIR / f"mealplanner_{identifier}.db"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(f"No backup matching '{identifier}' in {BACKUP_DIR}")


def do_restore(target: Path, confirmed: bool) -> None:
    db_path = Path(settings.database_path)

    print(f"Backup to restore: {target}")
    print(f"Will overwrite:    {db_path}")

    if not confirmed:
        print("\nDry run only - nothing changed. Re-run with --yes to actually restore.")
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        pre_restore = db_path.with_name(f"{db_path.stem}.pre-restore-{stamp}{db_path.suffix}")
        shutil.copy2(db_path, pre_restore)
        logger.info("Restore: saved pre-restore safety copy to %s", pre_restore)
        print(f"Saved current database to {pre_restore} before overwriting.")

    shutil.copy2(target, db_path)
    logger.info("Restore: restored %s -> %s", target, db_path)
    print(f"Restored. {db_path} now matches {target.name}.")


def main(argv: list[str]) -> int:
    if not argv:
        backups = list_backups()
        if not backups:
            print(f"No backups found in {BACKUP_DIR}. Run scripts/backup.py first.")
            return 1
        print(f"Available backups in {BACKUP_DIR}:")
        for b in backups:
            print(f"  {b.stem.removeprefix('mealplanner_')}")
        print("\nRestore with: python -m scripts.restore <timestamp|latest> [--yes]")
        return 0

    identifier = argv[0]
    confirmed = "--yes" in argv[1:]

    try:
        target = resolve_target(identifier)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    do_restore(target, confirmed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

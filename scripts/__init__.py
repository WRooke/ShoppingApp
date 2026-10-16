"""Maintenance scripts (backup/restore). Run as modules from the project root:

    python -m scripts.backup
    python -m scripts.restore [backup_id]

so that ``app`` is importable — see backup.bat / restore.bat.

Branch model used by deploy / update / backup (the NUC = the always-on mini PC that hosts the app;
the dev PC = where changes are made):
  * ``develop``    — all changes are made and tested here, on the dev PC.
  * ``production`` — what the NUC runs; moved only by ``deploy`` (after the tests pass).
  * Weekly backups are committed on ``production`` by the NUC.
Full description: docs/deployment-and-operations.md.
"""

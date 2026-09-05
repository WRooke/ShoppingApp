"""Small shared subprocess helper for the git-based deploy/backup scripts.

Kept dependency-free (stdlib only) so it works the moment .venv exists, before any
requirements are installed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(cwd: Path, *args: str, timeout: int = 30) -> tuple[bool, str]:
    """Run ``git <args>`` in ``cwd``. Returns (success, combined stdout+stderr, stripped)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return False, "git executable not found on PATH"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

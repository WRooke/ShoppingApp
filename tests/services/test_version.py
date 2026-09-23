"""Unit tests for app/services/version.py — see CLAUDE.md > UI/UX > Client auto-update
notification. `subprocess.run` is mocked throughout; no real git process needed.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from app.services import version as version_module


def _reset_cache():
    version_module._cached_version = None


def test_get_version_returns_git_describe_output():
    _reset_cache()
    fake_result = MagicMock(stdout="release-20260923-000000\n")
    with patch("app.services.version.subprocess.run", return_value=fake_result):
        assert version_module.get_version() == "release-20260923-000000"


def test_get_version_caches_after_first_call():
    _reset_cache()
    fake_result = MagicMock(stdout="v1\n")
    with patch("app.services.version.subprocess.run", return_value=fake_result) as mock_run:
        first = version_module.get_version()
        second = version_module.get_version()
    assert first == second == "v1"
    mock_run.assert_called_once()


def test_get_version_falls_back_to_dev_when_git_unavailable():
    _reset_cache()
    with patch(
        "app.services.version.subprocess.run",
        side_effect=FileNotFoundError("git not found"),
    ):
        assert version_module.get_version() == "dev"


def test_get_version_falls_back_to_dev_on_nonzero_exit():
    _reset_cache()
    with patch(
        "app.services.version.subprocess.run",
        side_effect=subprocess.CalledProcessError(128, "git"),
    ):
        assert version_module.get_version() == "dev"

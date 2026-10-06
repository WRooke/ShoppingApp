"""Unit tests for app/services/version.py — the build identity the client auto-update banner
compares (docs/deployment-and-operations.md > "How an open phone learns the NUC was updated").

The point of the 2026-10-06 rewrite: the id is a hash of the CODE, so it needs no git, cannot fall
back to a constant, and changes exactly when the code changes. Git is only a display label.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.services import version as version_module


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(version_module.ENV_BUILD_ID, raising=False)
    monkeypatch.delenv(version_module.ENV_STATIC_DIR, raising=False)
    version_module.reset_for_tests()
    yield
    version_module.reset_for_tests()


def _tree(root, files):
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode())
    return root


def test_build_id_is_deterministic_and_short(tmp_path):
    _tree(tmp_path, {"app/a.py": "x = 1", "static/js/b.js": "var b;"})
    one = version_module.compute_build_id(tmp_path)
    assert one == version_module.compute_build_id(tmp_path)
    assert len(one) == 12 and all(c in "0123456789abcdef" for c in one)


def test_build_id_changes_when_any_served_or_running_file_changes(tmp_path):
    _tree(tmp_path, {"app/a.py": "x = 1", "static/js/b.js": "var b;", "static/css/c.css": "a{}"})
    base = version_module.compute_build_id(tmp_path)
    (tmp_path / "static/js/b.js").write_text("var b = 2;")
    changed_js = version_module.compute_build_id(tmp_path)
    assert changed_js != base
    (tmp_path / "app/a.py").write_text("x = 2")
    assert version_module.compute_build_id(tmp_path) not in (base, changed_js)


def test_build_id_covers_added_removed_and_renamed_files(tmp_path):
    _tree(tmp_path, {"static/js/b.js": "var b;"})
    base = version_module.compute_build_id(tmp_path)
    (tmp_path / "static/js/new.js").write_text("var n;")
    added = version_module.compute_build_id(tmp_path)
    assert added != base
    (tmp_path / "static/js/new.js").rename(tmp_path / "static/js/renamed.js")
    assert version_module.compute_build_id(tmp_path) != added  # same bytes, different path
    (tmp_path / "static/js/renamed.js").unlink()
    assert version_module.compute_build_id(tmp_path) == base


def test_build_id_ignores_what_does_not_affect_the_running_app(tmp_path):
    _tree(tmp_path, {"app/a.py": "x = 1", "static/js/b.js": "var b;"})
    base = version_module.compute_build_id(tmp_path)
    _tree(tmp_path, {"docs/readme.md": "docs", "tests/t.py": "t", "app/__pycache__/a.pyc": b"\x00\x01",
                     "app/x.pyc": b"\x02"})
    assert version_module.compute_build_id(tmp_path) == base  # a docs/tests-only pull must not nag phones


def test_build_id_with_no_code_dirs_is_still_a_stable_value(tmp_path):
    assert version_module.compute_build_id(tmp_path) == version_module.compute_build_id(tmp_path)


def test_static_override_is_what_gets_hashed(tmp_path):
    _tree(tmp_path / "base", {"app/a.py": "x"})
    _tree(tmp_path / "other", {"js/b.js": "v1"})
    a = version_module.compute_build_id(tmp_path / "base", tmp_path / "other")
    (tmp_path / "other/js/b.js").write_text("v2")
    assert version_module.compute_build_id(tmp_path / "base", tmp_path / "other") != a


def test_env_override_pins_the_build_id_and_the_info_is_cached(monkeypatch):
    monkeypatch.setenv(version_module.ENV_BUILD_ID, "pinned-123")
    with patch("app.services.version.subprocess.run", side_effect=FileNotFoundError("no git")):
        info = version_module.get_build_info()
        assert info.build_id == "pinned-123" == version_module.get_build_id()
        assert version_module.get_build_info() is info  # computed once per process
    assert len(info.boot_id) == 12 and info.started_at.endswith("+00:00")


def test_static_dir_env_points_the_hash_at_an_editable_copy(monkeypatch, tmp_path):
    _tree(tmp_path / "copy", {"js/b.js": "v1"})
    monkeypatch.setenv(version_module.ENV_STATIC_DIR, str(tmp_path / "copy"))
    assert version_module.static_dir() == tmp_path / "copy"
    first = version_module.get_build_id()
    version_module.reset_for_tests()
    (tmp_path / "copy/js/b.js").write_text("v2")
    assert version_module.get_build_id() != first


def test_boot_id_differs_per_process_start():
    first = version_module.get_build_info().boot_id
    version_module.reset_for_tests()
    assert version_module.get_build_info().boot_id != first


# --- the git label: best effort, never affects the build id -----------------------------------


def test_label_is_git_describe_when_available():
    fake = MagicMock(stdout="release-20260923-000000\n")
    with patch("app.services.version.subprocess.run", return_value=fake) as run:
        assert version_module.get_version() == "release-20260923-000000"
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["git", "-c", cmd[2]] and cmd[2].startswith("safe.directory=")  # no "dubious ownership"


@pytest.mark.parametrize("error", [
    FileNotFoundError("git not on PATH"),
    subprocess.CalledProcessError(128, "git"),
    subprocess.TimeoutExpired("git", 5),
    PermissionError("denied"),
])
def test_a_broken_git_costs_only_the_label_never_the_build_id(error):
    real_id = version_module.compute_build_id()
    with patch("app.services.version.subprocess.run", side_effect=error):
        info = version_module.get_build_info()
    assert info.label == "unknown" and info.label_source == "unavailable"
    assert info.build_id == real_id and info.build_id != "dev"  # the old failure mode: constant "dev"


def test_empty_git_output_is_treated_as_unavailable():
    with patch("app.services.version.subprocess.run", return_value=MagicMock(stdout="  \n")):
        assert version_module.get_build_info().label_source == "unavailable"

"""Unit tests for app/config.py — the Phase 5 hybrid AnyList credential resolver
(CLAUDE.md > Security §2). keyring is monkeypatched; no real Credential Manager access.
"""

from __future__ import annotations

import keyring
import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clear_anylist_env(monkeypatch):
    for var in (
        "ANYLIST_EMAIL",
        "ANYLIST_PASSWORD",
        "ANYLIST_ENABLED",
        "ANYLIST_FAKE_MODE",
        "ANYLIST_TARGET_LIST_NAME",
    ):
        monkeypatch.delenv(var, raising=False)


def _stub_keyring(monkeypatch, mapping: dict[str, str | None]):
    monkeypatch.setattr(
        keyring, "get_password", lambda service, key: mapping.get(key), raising=True
    )


def test_keyring_wins_when_both_present(monkeypatch):
    _stub_keyring(monkeypatch, {"anylist_email": "kr@example.com", "anylist_password": "krpw"})
    monkeypatch.setenv("ANYLIST_EMAIL", "env@example.com")
    monkeypatch.setenv("ANYLIST_PASSWORD", "envpw")
    s = Settings()
    assert s.anylist_email == "kr@example.com"
    assert s.anylist_password == "krpw"
    assert s.anylist_secret_source == "keyring"


def test_falls_back_to_env_when_keyring_empty(monkeypatch):
    _stub_keyring(monkeypatch, {})
    monkeypatch.setenv("ANYLIST_EMAIL", "env@example.com")
    monkeypatch.setenv("ANYLIST_PASSWORD", "envpw")
    s = Settings()
    assert s.anylist_email == "env@example.com"
    assert s.anylist_password == "envpw"
    assert s.anylist_secret_source == "env"


def test_missing_everywhere(monkeypatch):
    _stub_keyring(monkeypatch, {})
    s = Settings()
    assert s.anylist_email == "" and s.anylist_password == ""
    assert s.anylist_secret_source == "missing"
    assert s.anylist_configured is False


def test_placeholder_env_is_not_treated_as_configured(monkeypatch):
    _stub_keyring(monkeypatch, {})
    monkeypatch.setenv("ANYLIST_EMAIL", "REPLACE_ME")
    monkeypatch.setenv("ANYLIST_PASSWORD", "REPLACE_ME")
    s = Settings()
    assert s.anylist_secret_source == "missing"  # REPLACE_ME is not "real"
    assert s.anylist_configured is False


def test_keyring_failure_degrades_to_env(monkeypatch):
    def _boom(service, key):
        raise RuntimeError("credential store locked")

    monkeypatch.setattr(keyring, "get_password", _boom, raising=True)
    monkeypatch.setenv("ANYLIST_EMAIL", "env@example.com")
    monkeypatch.setenv("ANYLIST_PASSWORD", "envpw")
    s = Settings()
    assert s.anylist_email == "env@example.com"
    assert s.anylist_secret_source == "env"


def test_gates_default_off_and_target_list_defaults(monkeypatch):
    _stub_keyring(monkeypatch, {})
    s = Settings()
    assert s.anylist_enabled is False
    assert s.anylist_fake_mode is False
    assert s.anylist_target_list_name == "TestList"


def test_gates_parse_narrow_true(monkeypatch):
    _stub_keyring(monkeypatch, {})
    monkeypatch.setenv("ANYLIST_ENABLED", "TRUE")
    monkeypatch.setenv("ANYLIST_FAKE_MODE", "yes")
    monkeypatch.setenv("ANYLIST_TARGET_LIST_NAME", "  MyTestList  ")
    s = Settings()
    assert s.anylist_enabled is True
    assert s.anylist_fake_mode is True
    assert s.anylist_target_list_name == "MyTestList"


def test_gate_typo_fails_safe_to_false(monkeypatch):
    _stub_keyring(monkeypatch, {})
    monkeypatch.setenv("ANYLIST_ENABLED", "ture")  # typo
    s = Settings()
    assert s.anylist_enabled is False

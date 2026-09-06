"""Configuration loading.

Reads the project-root .env file once at import time and exposes a single
``settings`` object. Paths from the environment are resolved to absolute paths
relative to the project root so the app behaves the same regardless of the
working directory it is launched from.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _resolve(path_str: str) -> str:
    p = Path(path_str)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p.resolve())


class Settings:
    """Typed view over environment configuration."""

    def __init__(self) -> None:
        self.port: int = int(os.getenv("PORT", "8080"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # CORS (see CLAUDE.md > Security §4). Comma-separated exact origins the browser is
        # allowed to call this API cross-origin from. Defaults cover local dev only; the NUC
        # deployment should set this to http://<nuc-static-ip>:8080 once step 5 of SETUP.md
        # assigns that address, rather than leaving it wide open to any origin.
        self.allowed_origins: list[str] = [
            o.strip()
            for o in os.getenv(
                "ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
            ).split(",")
            if o.strip()
        ]

        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.anylist_email: str = os.getenv("ANYLIST_EMAIL", "").strip()
        self.anylist_password: str = os.getenv("ANYLIST_PASSWORD", "").strip()

        # Gate on real Claude API calls — see CLAUDE.md > Security > §0c. Defaults OFF: a real
        # call is refused even with a valid key unless this is explicitly set to true. Claude
        # Code must never flip this to true in .env on its own initiative. (A hard AU$0.50
        # spend cap used to sit alongside this switch, in a `max_api_spend_aud_cents` setting
        # here — removed 2026-09-06, see CLAUDE.md's Non-Negotiable Operating Rules banner and
        # Security §0b; Anthropic billing is prepaid, so there was no runaway-invoice scenario
        # for an in-app dollar ceiling to guard against.)
        self.claude_api_enabled: bool = self._as_bool(os.getenv("CLAUDE_API_ENABLED", "false"))

        # Dev-only escape hatch that bypasses both gates above entirely by never calling the
        # real API at all — see CLAUDE.md > Security > §0c. When true, extract_ingredients()
        # returns a canned fixture, zero cost, zero network. Must never be true on the NUC.
        self.claude_api_fake_mode: bool = self._as_bool(os.getenv("CLAUDE_API_FAKE_MODE", "false"))

        self.database_path: str = _resolve(os.getenv("DATABASE_PATH", "data/mealplanner.db"))
        self.images_path: str = _resolve(os.getenv("IMAGES_PATH", "images"))
        self.logs_path: str = _resolve(os.getenv("LOGS_PATH", "logs"))

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _is_real(value: str) -> bool:
        """True when a secret looks filled in rather than a placeholder."""
        return bool(value) and "REPLACE_ME" not in value

    @staticmethod
    def _as_bool(value: str) -> bool:
        """Parses an env var as a boolean. Deliberately narrow — only these exact strings
        count as true — so a typo in .env fails safe (reads as false) rather than silently
        enabling a highest-priority gate (see CLAUDE.md > Security > §0c)."""
        return value.strip().lower() in ("1", "true", "yes", "on")

    @property
    def anthropic_configured(self) -> bool:
        return self._is_real(self.anthropic_api_key)

    @property
    def anylist_configured(self) -> bool:
        return self._is_real(self.anylist_email) and self._is_real(self.anylist_password)

    @property
    def summary(self) -> dict:
        """Non-secret snapshot for the health endpoint and diagnostics."""
        return {
            "port": self.port,
            "log_level": self.log_level,
            "allowed_origins": self.allowed_origins,
            "database_path": self.database_path,
            "images_path": self.images_path,
            "logs_path": self.logs_path,
            "anthropic_api_key_configured": self.anthropic_configured,
            "anylist_credentials_configured": self.anylist_configured,
            "claude_api_enabled": self.claude_api_enabled,
            "claude_api_fake_mode": self.claude_api_fake_mode,
        }


settings = Settings()

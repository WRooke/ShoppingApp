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

        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.anylist_email: str = os.getenv("ANYLIST_EMAIL", "").strip()
        self.anylist_password: str = os.getenv("ANYLIST_PASSWORD", "").strip()

        self.database_path: str = _resolve(os.getenv("DATABASE_PATH", "data/mealplanner.db"))
        self.images_path: str = _resolve(os.getenv("IMAGES_PATH", "images"))
        self.logs_path: str = _resolve(os.getenv("LOGS_PATH", "logs"))

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _is_real(value: str) -> bool:
        """True when a secret looks filled in rather than a placeholder."""
        return bool(value) and "REPLACE_ME" not in value

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
            "database_path": self.database_path,
            "images_path": self.images_path,
            "logs_path": self.logs_path,
            "anthropic_api_key_configured": self.anthropic_configured,
            "anylist_credentials_configured": self.anylist_configured,
        }


settings = Settings()

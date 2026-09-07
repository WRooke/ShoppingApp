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

# Windows Credential Manager service name for the AnyList credentials (Phase 5, hybrid
# storage — see CLAUDE.md > Security §2). Set them once with:
#   keyring set shoppingapp anylist_email     / keyring set shoppingapp anylist_password
_KEYRING_SERVICE = "shoppingapp"


def _from_keyring(key: str) -> str | None:
    """Read one secret from the OS keyring. Returns None (and never raises) if the keyring
    package is missing, the backend is unavailable/locked, or the key isn't set — the caller
    falls back to the .env var in every one of those cases."""
    try:
        import keyring  # imported lazily so a broken backend can't break app import

        value = keyring.get_password(_KEYRING_SERVICE, key)
        return value.strip() if value else None
    except Exception:  # noqa: BLE001 — any keyring failure must degrade to the .env fallback
        return None


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

        # AI recipe extraction — Google Gemini as of Phase 3.9 (was Anthropic Claude). See
        # CLAUDE.md > AI Provider Migration. Env vars renamed at M1; §0c semantics unchanged.
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()

        # AnyList credentials (Phase 5) — hybrid storage per CLAUDE.md > Security §2: try the
        # OS keyring (Windows Credential Manager) first, fall back to the .env vars. Each
        # secret falls back independently. `anylist_secret_source` records where the pair
        # actually came from so app.main can log a one-time WARNING about the plaintext
        # fallback *after* logging is configured (it isn't yet, here at import time).
        kr_email, kr_password = _from_keyring("anylist_email"), _from_keyring("anylist_password")
        env_email = os.getenv("ANYLIST_EMAIL", "").strip()
        env_password = os.getenv("ANYLIST_PASSWORD", "").strip()
        self.anylist_email: str = kr_email or env_email
        self.anylist_password: str = kr_password or env_password
        if kr_email and kr_password:
            self.anylist_secret_source = "keyring"
        elif self._is_real(self.anylist_email) or self._is_real(self.anylist_password):
            self.anylist_secret_source = "env" if not (kr_email or kr_password) else "mixed"
        else:
            self.anylist_secret_source = "missing"

        # Gate on real AnyList calls + offline fake-list mode (Phase 5) — mirrors §0c for the
        # AI. Both default OFF; no agent flips ANYLIST_ENABLED. ANYLIST_TARGET_LIST_NAME is
        # the dev test list — the real household list is never the target without a fresh,
        # explicit go-ahead. See CLAUDE.md > Security §2 and > Build Phases > Phase 5.
        self.anylist_enabled: bool = self._as_bool(os.getenv("ANYLIST_ENABLED", "false"))
        self.anylist_fake_mode: bool = self._as_bool(os.getenv("ANYLIST_FAKE_MODE", "false"))
        self.anylist_target_list_name: str = os.getenv(
            "ANYLIST_TARGET_LIST_NAME", "TestList"
        ).strip() or "TestList"

        # Gate on real Gemini API calls — see CLAUDE.md > Security > §0c. Defaults OFF: a real
        # call is refused even with a valid key unless this is explicitly set to true. An agent
        # session must never flip this to true in .env on its own initiative. (A hard AU$0.50
        # spend cap used to sit alongside the old CLAUDE_API_ENABLED switch — removed
        # 2026-09-06; and Gemini's free tier has no per-call dollar cost at all.)
        self.ai_extraction_enabled: bool = self._as_bool(
            os.getenv("AI_EXTRACTION_ENABLED", "false")
        )

        # Dev-only escape hatch that bypasses both gates above entirely by never calling the
        # real API at all — see CLAUDE.md > Security > §0c. When true, the extraction calls
        # return a canned fixture, zero cost, zero network. Must never be true on the NUC.
        self.ai_extraction_fake_mode: bool = self._as_bool(
            os.getenv("AI_EXTRACTION_FAKE_MODE", "false")
        )

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
    def gemini_configured(self) -> bool:
        return self._is_real(self.gemini_api_key)

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
            "gemini_api_key_configured": self.gemini_configured,
            "anylist_credentials_configured": self.anylist_configured,
            "anylist_secret_source": self.anylist_secret_source,
            "anylist_enabled": self.anylist_enabled,
            "anylist_fake_mode": self.anylist_fake_mode,
            "anylist_target_list_name": self.anylist_target_list_name,
            "ai_extraction_enabled": self.ai_extraction_enabled,
            "ai_extraction_fake_mode": self.ai_extraction_fake_mode,
        }


settings = Settings()

"""Request body for ``POST /api/v1/client-log`` — see app/services/client_log.py."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientLogReport(BaseModel):
    """One error the browser hit. Everything is bounded here AND again in the service: the
    endpoint is unauthenticated (LAN-only, CLAUDE.md > Security §1), so its input is untrusted."""

    kind: str = Field(default="error", max_length=40)  # error | unhandledrejection | api | route | other
    message: str = Field(default="", max_length=2000)
    stack: str | None = Field(default=None, max_length=20000)
    url: str | None = Field(default=None, max_length=2000)  # the page the user was on
    build: str | None = Field(default=None, max_length=80)  # the build id the page was loaded with

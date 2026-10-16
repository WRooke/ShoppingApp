"""Pydantic request/response models — the API's actual contract.

Kept separate from the SQLAlchemy ORM models in ``app.models`` on purpose: an
internal column can be renamed, split, or soft-deleted without every response
shape changing, and vice versa. Routers import from here, never expose a raw
ORM object as a response body.

One file per feature area, mirroring ``app.routers``. Request and response
models live here (recipes, plans, checklist, settings, AI extraction and more).

See docs/code-architecture.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

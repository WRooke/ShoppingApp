"""Pydantic request/response models — the API's actual contract.

Kept separate from the SQLAlchemy ORM models in ``app.models`` on purpose: an
internal column can be renamed, split, or soft-deleted without every response
shape changing, and vice versa. Routers import from here, never expose a raw
ORM object as a response body.

One file per feature area, mirroring ``app.routers``. Empty for now — the
first real schemas land with Phase 2 (recipe CRUD).

See CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

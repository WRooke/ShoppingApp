"""Photo-based recipe capture — store the uploaded image, hand it to Claude as base64.

See CLAUDE.md > Recipe Capture — AI Extraction > Photo capture flow. Plain Python only, no
`fastapi` import — see CLAUDE.md > Code Architecture & Maintainability.
"""

from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.services import ai_extraction

logger = logging.getLogger(__name__)

# CLAUDE.md > Recipe Capture says "JPEG or PNG" — enforced here, not left to the frontend.
_ALLOWED_CONTENT_TYPES = {"image/jpeg": "jpg", "image/png": "png"}

# Defensive ceiling — not in CLAUDE.md explicitly, but an unbounded upload is both a disk-
# space and (via a larger image payload) cost-estimation risk. 10MB comfortably covers a
# phone camera photo at any sane resolution/compression.
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class InvalidImageError(Exception):
    """Raised for an unsupported content type, empty upload, or oversized file. Callers
    translate this to the {"ok": false, "error": ...} envelope."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def store_image(content: bytes, content_type: str) -> str:
    """Validate + store the upload under `images/` with a UUID filename; return the filename.
    Raises InvalidImageError before touching disk if the upload itself is bad. Split from the
    extract call (Phase 3.9 M3) so the capture endpoint keeps the filename even when the AI
    call is then queued on a 429."""
    extension = _ALLOWED_CONTENT_TYPES.get(content_type)
    if extension is None:
        raise InvalidImageError(
            f"Unsupported image type {content_type!r} — please use JPEG or PNG."
        )
    if not content:
        raise InvalidImageError("The uploaded image was empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise InvalidImageError(
            f"Image is too large ({len(content)} bytes) — the limit is {MAX_IMAGE_BYTES} bytes."
        )

    filename = f"{uuid.uuid4()}.{extension}"
    images_dir = Path(settings.images_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / filename).write_bytes(content)
    logger.info("Recipe photo stored: %s (%d bytes)", filename, len(content))
    return filename


def extract_stored(
    db: Session, *, filename: str, content: bytes, content_type: str
) -> ai_extraction.ExtractionResult:
    """Run the 3-call capture pipeline on an already-stored image."""
    return ai_extraction.capture_recipe(
        db,
        call_type="recipe_photo",
        context_id=filename,
        image_base64=base64.standard_b64encode(content).decode("utf-8"),
        image_media_type=content_type,
    )


def store_and_extract(
    db: Session, *, content: bytes, content_type: str
) -> tuple[str, ai_extraction.ExtractionResult]:
    """store_image() + extract_stored() in one call. Returns (filename, result)."""
    filename = store_image(content, content_type)
    result = extract_stored(db, filename=filename, content=content, content_type=content_type)
    return filename, result

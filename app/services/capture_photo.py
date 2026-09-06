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
from app.services import claude_client

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


def store_and_extract(
    db: Session, *, content: bytes, content_type: str
) -> tuple[str, claude_client.ExtractionResult]:
    """Validates and stores the image under `images/` with a UUID filename, then calls
    claude_client.extract_ingredients() with call_type='recipe_photo'. Returns
    (stored_filename, extraction_result). Raises InvalidImageError before ever touching disk
    or calling out if the upload itself is bad."""
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

    image_base64 = base64.standard_b64encode(content).decode("utf-8")
    result = claude_client.extract_ingredients(
        db,
        call_type="recipe_photo",
        context_id=filename,
        image_base64=image_base64,
        image_media_type=content_type,
    )
    return filename, result

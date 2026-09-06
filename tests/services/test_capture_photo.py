"""Unit tests for app/services/capture_photo.py. ai_extraction is mocked — no network, no
Claude call, per CLAUDE.md > Code Architecture & Maintainability > Tests. Images are written
to conftest.py's temp IMAGES_PATH, not the real project images/ directory.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import settings
from app.services.capture_photo import InvalidImageError, store_and_extract


def test_store_and_extract_saves_file_and_calls_ai():
    with patch("app.services.capture_photo.ai_extraction.extract_ingredients") as mock_extract:
        mock_extract.return_value = "dummy-result"
        filename, result = store_and_extract(
            "fake-db", content=b"fake-jpeg-bytes", content_type="image/jpeg"
        )

    assert result == "dummy-result"
    assert filename.endswith(".jpg")
    saved_path = Path(settings.images_path) / filename
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"fake-jpeg-bytes"

    _, kwargs = mock_extract.call_args
    assert kwargs["call_type"] == "recipe_photo"
    assert kwargs["context_id"] == filename
    assert kwargs["image_media_type"] == "image/jpeg"
    assert kwargs["image_base64"]  # non-empty


def test_store_and_extract_accepts_png():
    with patch("app.services.capture_photo.ai_extraction.extract_ingredients"):
        filename, _ = store_and_extract("fake-db", content=b"fake-png", content_type="image/png")
    assert filename.endswith(".png")


def test_store_and_extract_rejects_unsupported_content_type():
    with pytest.raises(InvalidImageError):
        store_and_extract("fake-db", content=b"whatever", content_type="image/gif")


def test_store_and_extract_rejects_empty_content():
    with pytest.raises(InvalidImageError):
        store_and_extract("fake-db", content=b"", content_type="image/jpeg")


def test_store_and_extract_rejects_oversized_content():
    from app.services.capture_photo import MAX_IMAGE_BYTES

    with pytest.raises(InvalidImageError):
        store_and_extract(
            "fake-db", content=b"x" * (MAX_IMAGE_BYTES + 1), content_type="image/jpeg"
        )


def test_store_and_extract_never_touches_disk_or_claude_for_invalid_image():
    with patch("app.services.capture_photo.ai_extraction.extract_ingredients") as mock_extract:
        with pytest.raises(InvalidImageError):
            store_and_extract("fake-db", content=b"x", content_type="image/gif")
        mock_extract.assert_not_called()

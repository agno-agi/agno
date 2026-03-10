"""Tests for Step._convert_image_artifacts_to_images handling of raw and base64 image bytes."""

import base64
from unittest.mock import MagicMock

import pytest

from agno.media import Image
from agno.workflow.step import Step


@pytest.fixture()
def step():
    mock_agent = MagicMock()
    mock_agent.id = "test-agent"
    return Step(name="test", agent=mock_agent)


class TestConvertImageArtifactsToImages:
    def test_raw_jpeg_bytes_not_dropped(self, step):
        """Raw JPEG bytes should be preserved, not silently skipped."""
        raw_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        images = step._convert_image_artifacts_to_images([Image(content=raw_jpeg)])
        assert len(images) == 1
        assert images[0].content == raw_jpeg

    def test_raw_png_bytes_not_dropped(self, step):
        """Raw PNG bytes should be preserved, not silently skipped."""
        raw_png = b"\x89PNG\r\n\x1a\n\x00\x00"
        images = step._convert_image_artifacts_to_images([Image(content=raw_png)])
        assert len(images) == 1
        assert images[0].content == raw_png

    def test_base64_encoded_bytes_decoded(self, step):
        """Base64-encoded bytes should be decoded to raw bytes."""
        original = b"test image data"
        b64_bytes = base64.b64encode(original)
        images = step._convert_image_artifacts_to_images([Image(content=b64_bytes)])
        assert len(images) == 1
        assert images[0].content == original

    def test_url_image_passes_through(self, step):
        """URL-based images should pass through unchanged."""
        images = step._convert_image_artifacts_to_images([Image(url="https://example.com/img.png")])
        assert len(images) == 1
        assert images[0].url == "https://example.com/img.png"

    def test_empty_list_returns_empty(self, step):
        """Empty input should return empty output."""
        images = step._convert_image_artifacts_to_images([])
        assert images == []

    def test_multiple_images_all_preserved(self, step):
        """Multiple images of different types should all be preserved."""
        raw_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        raw_png = b"\x89PNG\r\n\x1a\n\x00\x00"
        images = step._convert_image_artifacts_to_images(
            [
                Image(content=raw_jpeg),
                Image(content=raw_png),
                Image(url="https://example.com/img.png"),
            ]
        )
        assert len(images) == 3

    def test_image_with_mime_type_sets_format(self, step):
        """Image with mime_type should have format extracted."""
        raw_png = b"\x89PNG\r\n\x1a\n\x00\x00"
        images = step._convert_image_artifacts_to_images([Image(content=raw_png, mime_type="image/png")])
        assert len(images) == 1
        assert images[0].content == raw_png

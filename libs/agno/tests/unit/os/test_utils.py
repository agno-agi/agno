"""Unit tests for OS utility functions."""

import io
from datetime import datetime, timezone
from typing import Optional

import pytest
from starlette.datastructures import Headers, UploadFile

from agno.os.utils import (
    classify_upload_file,
    process_document,
    to_utc_datetime,
)


def test_returns_none_for_none_input():
    """Test that None input returns None."""
    assert to_utc_datetime(None) is None


def test_converts_int_timestamp():
    """Test conversion of integer Unix timestamp."""
    # Unix timestamp for 2024-01-01 00:00:00 UTC
    timestamp = 1704067200
    result = to_utc_datetime(timestamp)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1


def test_converts_float_timestamp():
    """Test conversion of float Unix timestamp with microseconds."""
    # Unix timestamp with fractional seconds
    timestamp = 1704067200.123456
    result = to_utc_datetime(timestamp)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.microsecond > 0


def test_preserves_utc_datetime():
    """Test that UTC datetime is returned as-is."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = to_utc_datetime(dt)

    assert result is dt


def test_adds_utc_to_naive_datetime():
    """Test that naive datetime gets UTC timezone added."""
    dt = datetime(2024, 1, 1, 12, 0, 0)
    result = to_utc_datetime(dt)

    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1
    assert result.hour == 12


def test_preserves_non_utc_timezone():
    """Test that datetime with non-UTC timezone is preserved."""
    from datetime import timedelta

    # Create a datetime with +5:30 offset (IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ist)
    result = to_utc_datetime(dt)

    # Should preserve the original timezone
    assert result == dt


def test_handles_zero_timestamp():
    """Test handling of zero timestamp (Unix epoch)."""
    result = to_utc_datetime(0)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 1970
    assert result.month == 1
    assert result.day == 1


def test_handles_negative_timestamp():
    """Test handling of negative timestamp (before Unix epoch)."""
    # One day before Unix epoch
    result = to_utc_datetime(-86400)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 1969
    assert result.month == 12
    assert result.day == 31


def _make_upload_file(filename: str, content_type: Optional[str], data: bytes = b"content") -> UploadFile:
    """Build an UploadFile mirroring what Starlette passes the routers from a multipart upload."""
    headers = Headers({"content-type": content_type}) if content_type is not None else Headers({})
    return UploadFile(filename=filename, file=io.BytesIO(data), headers=headers)


class TestClassifyUploadFile:
    """Tests for classify_upload_file, including the extension fallback for ambiguous content types."""

    @pytest.mark.parametrize(
        "content_type, filename, expected",
        [
            # Images / audio / video route by content type.
            ("image/png", "img.png", "image"),
            ("audio/wav", "clip.wav", "audio"),
            ("video/mp4", "movie.mp4", "video"),
            # Documents route by content type.
            ("application/pdf", "doc.pdf", "document"),
            ("text/markdown", "notes.md", "document"),
            (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "deck.pptx",
                "document",
            ),
        ],
    )
    def test_routes_known_content_types(self, content_type, filename, expected):
        assert classify_upload_file(_make_upload_file(filename, content_type)) == expected

    @pytest.mark.parametrize("content_type", ["application/octet-stream", "", None])
    def test_markdown_falls_back_to_extension(self, content_type):
        """Browsers often send .md as octet-stream/empty rather than text/markdown."""
        assert classify_upload_file(_make_upload_file("notes.md", content_type)) == "document"
        assert classify_upload_file(_make_upload_file("README.markdown", content_type)) == "document"

    @pytest.mark.parametrize("content_type", ["application/octet-stream", "", None])
    def test_pptx_falls_back_to_extension(self, content_type):
        assert classify_upload_file(_make_upload_file("deck.pptx", content_type)) == "document"

    def test_unsupported_type_returns_none(self):
        """Genuinely unsupported files must still be rejected (router raises 400)."""
        assert classify_upload_file(_make_upload_file("archive.zip", "application/zip")) is None
        assert classify_upload_file(_make_upload_file("mystery.xyz", "application/octet-stream")) is None
        assert classify_upload_file(_make_upload_file("noext", "application/octet-stream")) is None

    def test_specific_content_type_not_overridden_by_extension(self):
        """A recognised content type is trusted even if the extension disagrees."""
        # An image content type with a misleading .txt name is still an image.
        assert classify_upload_file(_make_upload_file("photo.txt", "image/png")) == "image"


class TestProcessDocumentMimeResolution:
    """process_document must build a FileMedia with a mime_type accepted by File.valid_mime_types()."""

    def test_markdown_with_octet_stream_gets_valid_mime(self):
        result = process_document(_make_upload_file("notes.md", "application/octet-stream", b"# Title"))
        assert result is not None
        assert result.mime_type == "text/markdown"
        assert result.format == "md"

    def test_pptx_with_octet_stream_gets_valid_mime(self):
        result = process_document(_make_upload_file("deck.pptx", "application/octet-stream", b"PK\x03\x04binary"))
        assert result is not None
        assert result.mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        assert result.format == "pptx"

    def test_known_content_type_is_preserved(self):
        result = process_document(_make_upload_file("doc.pdf", "application/pdf", b"%PDF-1.4"))
        assert result is not None
        assert result.mime_type == "application/pdf"

"""Unit tests for OS utility functions."""

import io
from datetime import datetime, timezone
from typing import Optional

import pytest
from starlette.datastructures import Headers, UploadFile

from agno.media import File
from agno.os.utils import (
    DOCUMENT_MIME_TYPES,
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


# Single source of truth for the document formats the API accepts: (extension, canonical MIME).
# Every entry must classify as "document" and produce a FileMedia accepted by File.valid_mime_types().
DOCUMENT_FORMATS = [
    ("doc.pdf", "application/pdf"),
    ("data.json", "application/json"),
    ("script.js", "text/javascript"),
    ("report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("report.doc", "application/msword"),
    ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("deck.ppt", "application/vnd.ms-powerpoint"),
    ("sheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("sheet.xls", "application/vnd.ms-excel"),
    ("email.msg", "application/vnd.ms-outlook"),
    ("module.py", "text/x-python"),
    ("readme.txt", "text/plain"),
    ("page.html", "text/html"),
    ("style.css", "text/css"),
    ("notes.md", "text/markdown"),
    ("data.csv", "text/csv"),
    ("feed.xml", "text/xml"),
    ("doc.rtf", "text/rtf"),
]


class TestClassifyUploadFile:
    """Tests for classify_upload_file, including the extension fallback for ambiguous content types."""

    @pytest.mark.parametrize(
        "content_type, filename, expected",
        [
            # Images / audio / video route by content type.
            ("image/png", "img.png", "image"),
            ("audio/wav", "clip.wav", "audio"),
            ("video/mp4", "movie.mp4", "video"),
        ],
    )
    def test_routes_known_media_content_types(self, content_type, filename, expected):
        assert classify_upload_file(_make_upload_file(filename, content_type)) == expected

    @pytest.mark.parametrize("filename, content_type", DOCUMENT_FORMATS)
    def test_all_document_content_types_route_to_document(self, filename, content_type):
        assert classify_upload_file(_make_upload_file(filename, content_type)) == "document"

    @pytest.mark.parametrize("filename, _content_type", DOCUMENT_FORMATS)
    @pytest.mark.parametrize("ambiguous", ["application/octet-stream", "", None])
    def test_documents_fall_back_to_extension(self, filename, _content_type, ambiguous):
        """Browsers often send documents (e.g. .md, .pptx) as octet-stream/empty rather than the real MIME."""
        assert classify_upload_file(_make_upload_file(filename, ambiguous)) == "document"

    def test_markdown_alternate_extension(self):
        assert classify_upload_file(_make_upload_file("README.markdown", "application/octet-stream")) == "document"

    def test_unsupported_type_returns_none(self):
        """Genuinely unsupported files must still be rejected (router raises 400)."""
        assert classify_upload_file(_make_upload_file("archive.zip", "application/zip")) is None
        assert classify_upload_file(_make_upload_file("mystery.xyz", "application/octet-stream")) is None
        assert classify_upload_file(_make_upload_file("noext", "application/octet-stream")) is None

    def test_specific_content_type_not_overridden_by_extension(self):
        """A recognised content type is trusted even if the extension disagrees."""
        # An image content type with a misleading .txt name is still an image.
        assert classify_upload_file(_make_upload_file("photo.txt", "image/png")) == "image"


class TestProcessDocument:
    """process_document must build a FileMedia with a mime_type accepted by File.valid_mime_types()."""

    @pytest.mark.parametrize("filename, content_type", DOCUMENT_FORMATS)
    def test_known_content_type_is_preserved(self, filename, content_type):
        result = process_document(_make_upload_file(filename, content_type, b"data"))
        assert result is not None
        assert result.mime_type == content_type

    @pytest.mark.parametrize("filename, content_type", DOCUMENT_FORMATS)
    def test_octet_stream_recovers_mime_from_extension(self, filename, content_type):
        """When the browser sends a generic content type, mime_type is recovered from the extension."""
        result = process_document(_make_upload_file(filename, "application/octet-stream", b"data"))
        assert result is not None
        assert result.mime_type == content_type
        assert result.format == filename.rsplit(".", 1)[-1]

    def test_empty_file_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            process_document(_make_upload_file("notes.md", "text/markdown", b""))
        assert exc_info.value.status_code == 400


class TestDocumentMimeTypesConsistency:
    """Guards the invariant that broke .msg: every accepted document type must be valid for FileMedia."""

    @pytest.mark.parametrize("mime_type", sorted(DOCUMENT_MIME_TYPES))
    def test_every_document_mime_type_is_valid_for_filemedia(self, mime_type):
        """If a type is in DOCUMENT_MIME_TYPES but not File.valid_mime_types(), uploads of that type
        return 200 but the file is silently dropped during FileMedia construction."""
        assert mime_type in File.valid_mime_types(), (
            f"{mime_type} is accepted by the upload routers but rejected by File.valid_mime_types(), "
            "so the file would be silently dropped. Add it to File.valid_mime_types()."
        )

    def test_constructing_filemedia_with_each_document_mime_type_succeeds(self):
        for mime_type in DOCUMENT_MIME_TYPES:
            # Should not raise.
            File(content=b"data", mime_type=mime_type)

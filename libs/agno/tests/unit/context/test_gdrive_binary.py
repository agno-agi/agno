"""
Unit test for binary file detection in GDrive read_file.

Verifies that read_file returns a clear error for binary MIME types
instead of returning garbage UTF-8 decoded bytes.
"""

from __future__ import annotations


import pytest

from agno.context.gdrive.tools import TEXT_EXCEPTIONS, _is_binary_mime


class TestBinaryMimeDetection:
    """Tests for _is_binary_mime helper."""

    @pytest.mark.parametrize(
        "mime_type",
        [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
            "application/vnd.ms-excel",  # .xls
            "application/msword",  # .doc
            "application/pdf",
            "application/zip",
            "application/octet-stream",
            "image/png",
            "image/jpeg",
            "video/mp4",
            "audio/mpeg",
        ],
    )
    def test_detects_binary_types(self, mime_type: str):
        assert _is_binary_mime(mime_type) is True

    @pytest.mark.parametrize(
        "mime_type",
        [
            "text/plain",
            "text/csv",
            "text/html",
            "application/json",
            "application/xml",
            "application/javascript",
            "text/markdown",
        ],
    )
    def test_allows_text_types(self, mime_type: str):
        assert _is_binary_mime(mime_type) is False

    def test_workspace_types_not_binary(self):
        # Workspace types are handled separately, not by _is_binary_mime
        assert _is_binary_mime("application/vnd.google-apps.document") is False
        assert _is_binary_mime("application/vnd.google-apps.spreadsheet") is False


class TestBinaryMimePrefixes:
    """Tests that BINARY_MIME_PREFIXES covers all expected formats."""

    def test_office_formats_covered(self):
        # Modern Office
        assert _is_binary_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert _is_binary_mime("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert _is_binary_mime("application/vnd.openxmlformats-officedocument.presentationml.presentation")
        # Legacy Office
        assert _is_binary_mime("application/vnd.ms-excel")
        assert _is_binary_mime("application/vnd.ms-powerpoint")
        assert _is_binary_mime("application/msword")

    def test_opendocument_formats_covered(self):
        # LibreOffice / OpenOffice
        assert _is_binary_mime("application/vnd.oasis.opendocument.text")
        assert _is_binary_mime("application/vnd.oasis.opendocument.spreadsheet")
        assert _is_binary_mime("application/vnd.oasis.opendocument.presentation")

    def test_apple_iwork_formats_covered(self):
        assert _is_binary_mime("application/vnd.apple.pages")
        assert _is_binary_mime("application/vnd.apple.numbers")
        assert _is_binary_mime("application/vnd.apple.keynote")

    def test_archive_formats_covered(self):
        assert _is_binary_mime("application/zip")
        assert _is_binary_mime("application/x-zip-compressed")
        assert _is_binary_mime("application/gzip")
        assert _is_binary_mime("application/x-tar")
        assert _is_binary_mime("application/vnd.rar")  # modern RAR
        assert _is_binary_mime("application/x-xz")
        assert _is_binary_mime("application/java-archive")  # .jar
        assert _is_binary_mime("application/vnd.android.package-archive")  # .apk

    def test_media_formats_covered(self):
        assert _is_binary_mime("image/png")
        assert _is_binary_mime("image/jpeg")
        assert _is_binary_mime("image/gif")
        assert _is_binary_mime("video/mp4")
        assert _is_binary_mime("video/quicktime")
        assert _is_binary_mime("audio/mpeg")
        assert _is_binary_mime("audio/wav")
        assert _is_binary_mime("font/woff2")

    def test_generic_binary_covered(self):
        assert _is_binary_mime("application/octet-stream")
        assert _is_binary_mime("application/pdf")

    def test_svg_is_text_exception(self):
        # SVG is XML text, should NOT be detected as binary
        assert not _is_binary_mime("image/svg+xml")
        assert "image/svg+xml" in TEXT_EXCEPTIONS

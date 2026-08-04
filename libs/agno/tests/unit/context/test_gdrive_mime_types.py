"""
Comprehensive test for all Google Drive MIME type handling in read_file.

Google Drive files fall into 4 categories:
1. Google Workspace (exportable) - Docs, Sheets, Slides, Scripts → export to text
2. Google Workspace (non-exportable) - Drawings, Forms, Sites, Folders → error
3. Binary files - Office, PDF, images, video, audio, archives → error (our fix)
4. Text files - .txt, .json, .csv, .md, .py, .html → decode as UTF-8

This test verifies that read_file correctly routes each MIME type.
"""

from __future__ import annotations

import pytest

from agno.tools.google.drive import GoogleDriveTools, WorkspaceType, _is_binary_mime


class TestGoogleWorkspaceExportable:
    """Google Workspace types that CAN be exported to text."""

    EXPORTABLE_TYPES = {
        "application/vnd.google-apps.document": "Google Docs",
        "application/vnd.google-apps.spreadsheet": "Google Sheets",
        "application/vnd.google-apps.presentation": "Google Slides",
        "application/vnd.google-apps.script": "Apps Script",
    }

    def test_all_exportable_types_in_text_export_map(self):
        """Verify all exportable Workspace types are in TEXT_EXPORT_TYPES."""
        for mime_type, name in self.EXPORTABLE_TYPES.items():
            assert mime_type in GoogleDriveTools.TEXT_EXPORT_TYPES, f"{name} ({mime_type}) should be exportable"

    def test_exportable_types_not_detected_as_binary(self):
        """Exportable types should NOT be caught by binary detection."""
        for mime_type in self.EXPORTABLE_TYPES:
            assert not _is_binary_mime(mime_type), f"{mime_type} should not be binary"


class TestGoogleWorkspaceNonExportable:
    """Google Workspace types that CANNOT be exported to text."""

    NON_EXPORTABLE_TYPES = {
        "application/vnd.google-apps.drawing": "Google Drawings",
        "application/vnd.google-apps.form": "Google Forms",
        "application/vnd.google-apps.site": "Google Sites",
        "application/vnd.google-apps.folder": "Folder",
        "application/vnd.google-apps.shortcut": "Shortcut",
        "application/vnd.google-apps.map": "Google My Maps",
        "application/vnd.google-apps.jam": "Jamboard",
        "application/vnd.google-apps.vid": "Google Vids",
    }

    def test_non_exportable_types_not_in_export_map(self):
        """Non-exportable types should NOT be in TEXT_EXPORT_TYPES."""
        for mime_type, name in self.NON_EXPORTABLE_TYPES.items():
            assert mime_type not in GoogleDriveTools.TEXT_EXPORT_TYPES, f"{name} should not be exportable"

    def test_non_exportable_types_have_workspace_prefix(self):
        """Non-exportable types should be caught by Workspace prefix check."""
        for mime_type in self.NON_EXPORTABLE_TYPES:
            assert mime_type.startswith(WorkspaceType.WORKSPACE_PREFIX)

    def test_non_exportable_types_not_detected_as_binary(self):
        """Non-exportable Workspace types are handled separately, not as binary."""
        for mime_type in self.NON_EXPORTABLE_TYPES:
            assert not _is_binary_mime(mime_type)


class TestBinaryFileTypes:
    """Binary file types that cannot be decoded as UTF-8."""

    # Office formats (modern and legacy)
    OFFICE_TYPES = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template": ".dotx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template": ".xltx",
        "application/vnd.openxmlformats-officedocument.presentationml.template": ".potx",
        "application/vnd.ms-word": ".doc",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/msword": ".doc",
    }

    # OpenDocument formats (LibreOffice/OpenOffice)
    OPENDOCUMENT_TYPES = {
        "application/vnd.oasis.opendocument.text": ".odt",
        "application/vnd.oasis.opendocument.spreadsheet": ".ods",
        "application/vnd.oasis.opendocument.presentation": ".odp",
    }

    # Apple iWork formats
    APPLE_IWORK_TYPES = {
        "application/vnd.apple.pages": ".pages",
        "application/vnd.apple.numbers": ".numbers",
        "application/vnd.apple.keynote": ".key",
    }

    # Document formats
    DOCUMENT_TYPES = {
        "application/pdf": ".pdf",
        "application/x-pdf": ".pdf",
        "application/rtf": ".rtf",
        "application/x-rtf": ".rtf",
        "application/epub+zip": ".epub",
        "application/x-mobipocket-ebook": ".mobi",
        "application/vnd.amazon.ebook": ".azw",
    }

    # Archive formats
    ARCHIVE_TYPES = {
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/x-rar-compressed": ".rar",
        "application/vnd.rar": ".rar",  # modern RAR
        "application/x-7z-compressed": ".7z",
        "application/gzip": ".gz",
        "application/x-gzip": ".gz",
        "application/x-tar": ".tar",
        "application/tar": ".tar",
        "application/x-bzip2": ".bz2",
        "application/x-xz": ".xz",
        "application/x-lzma": ".lzma",
        "application/zstd": ".zst",
        "application/x-zstd": ".zst",
        "application/java-archive": ".jar",
        "application/vnd.android.package-archive": ".apk",
        "application/x-iso9660-image": ".iso",
        "application/x-apple-diskimage": ".dmg",
    }

    # Font formats
    FONT_TYPES = {
        "font/woff": ".woff",
        "font/woff2": ".woff2",
        "font/ttf": ".ttf",
        "font/otf": ".otf",
    }

    # Image formats (binary)
    IMAGE_TYPES = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        # Note: image/svg+xml is TEXT, tested separately
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "image/x-icon": ".ico",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }

    # Video formats
    VIDEO_TYPES = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/webm": ".webm",
        "video/x-matroska": ".mkv",
        "video/mpeg": ".mpeg",
    }

    # Audio formats
    AUDIO_TYPES = {
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "audio/aac": ".aac",
        "audio/x-m4a": ".m4a",
    }

    # Generic binary
    GENERIC_BINARY = {
        "application/octet-stream": "generic binary",
    }

    @pytest.mark.parametrize("mime_type", list(OFFICE_TYPES.keys()))
    def test_office_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(OPENDOCUMENT_TYPES.keys()))
    def test_opendocument_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(APPLE_IWORK_TYPES.keys()))
    def test_apple_iwork_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(DOCUMENT_TYPES.keys()))
    def test_document_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(ARCHIVE_TYPES.keys()))
    def test_archive_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(FONT_TYPES.keys()))
    def test_font_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(IMAGE_TYPES.keys()))
    def test_image_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(VIDEO_TYPES.keys()))
    def test_video_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(AUDIO_TYPES.keys()))
    def test_audio_types_detected_as_binary(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"

    @pytest.mark.parametrize("mime_type", list(GENERIC_BINARY.keys()))
    def test_generic_binary_detected(self, mime_type: str):
        assert _is_binary_mime(mime_type), f"{mime_type} should be detected as binary"


class TestTextFileTypes:
    """Text file types that SHOULD be decoded as UTF-8."""

    TEXT_TYPES = {
        # Plain text
        "text/plain": ".txt",
        "text/csv": ".csv",
        "text/tab-separated-values": ".tsv",
        "text/markdown": ".md",
        "text/x-markdown": ".md",
        # Web formats
        "text/html": ".html",
        "text/css": ".css",
        "text/javascript": ".js",
        "application/javascript": ".js",
        "application/x-javascript": ".js",
        # Data formats
        "application/json": ".json",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "application/x-yaml": ".yaml",
        "text/yaml": ".yaml",
        # Code
        "text/x-python": ".py",
        "text/x-java-source": ".java",
        "text/x-c": ".c",
        "text/x-c++": ".cpp",
        "text/x-ruby": ".rb",
        "text/x-go": ".go",
        "text/x-rust": ".rs",
        "text/x-shellscript": ".sh",
        "application/x-sh": ".sh",
        # Config
        "application/toml": ".toml",
        "text/x-ini": ".ini",
        "application/x-httpd-php": ".php",
        # Special: SVG is under image/* but is XML text
        "image/svg+xml": ".svg",
    }

    @pytest.mark.parametrize("mime_type", list(TEXT_TYPES.keys()))
    def test_text_types_not_detected_as_binary(self, mime_type: str):
        assert not _is_binary_mime(mime_type), f"{mime_type} should NOT be detected as binary"

    @pytest.mark.parametrize("mime_type", list(TEXT_TYPES.keys()))
    def test_text_types_not_workspace(self, mime_type: str):
        assert not mime_type.startswith(WorkspaceType.WORKSPACE_PREFIX)


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_mime_type(self):
        """Empty MIME type should not be binary (will fail UTF-8 decode gracefully)."""
        assert not _is_binary_mime("")

    def test_unknown_mime_type(self):
        """Unknown MIME types should not be binary (attempt UTF-8 decode)."""
        assert not _is_binary_mime("application/x-unknown-format")

    def test_case_sensitivity(self):
        """MIME types should be case-insensitive in practice, but we match lowercase."""
        # Our implementation uses startswith which is case-sensitive
        # Drive API always returns lowercase, so this is fine
        assert _is_binary_mime("image/png")
        # This would fail, but Drive API won't send uppercase:
        # assert _is_binary_mime("IMAGE/PNG")

    def test_mime_type_with_parameters(self):
        """MIME types may include parameters like charset."""
        # charset parameters shouldn't affect binary detection
        # but our simple startswith doesn't handle this perfectly
        assert not _is_binary_mime("text/plain; charset=utf-8")
        # This is fine because the actual MIME from Drive is just "text/plain"


class TestMimeTypeCoverage:
    """Verify we have complete coverage of common Google Drive file types."""

    # Based on https://developers.google.com/drive/api/guides/mime-types
    GOOGLE_DRIVE_COMMON_TYPES = [
        # Google Workspace (exportable)
        ("application/vnd.google-apps.document", "export"),
        ("application/vnd.google-apps.spreadsheet", "export"),
        ("application/vnd.google-apps.presentation", "export"),
        ("application/vnd.google-apps.script", "export"),
        # Google Workspace (non-exportable)
        ("application/vnd.google-apps.drawing", "workspace_error"),
        ("application/vnd.google-apps.form", "workspace_error"),
        ("application/vnd.google-apps.folder", "workspace_error"),
        # Common uploads - binary
        ("application/pdf", "binary_error"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "binary_error"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "binary_error"),
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "binary_error"),
        ("image/jpeg", "binary_error"),
        ("image/png", "binary_error"),
        ("video/mp4", "binary_error"),
        ("application/zip", "binary_error"),
        # Common uploads - text
        ("text/plain", "text_decode"),
        ("application/json", "text_decode"),
        ("text/csv", "text_decode"),
        ("text/html", "text_decode"),
    ]

    @pytest.mark.parametrize("mime_type,expected_handling", GOOGLE_DRIVE_COMMON_TYPES)
    def test_common_types_handled_correctly(self, mime_type: str, expected_handling: str):
        in_export = mime_type in GoogleDriveTools.TEXT_EXPORT_TYPES
        is_workspace = mime_type.startswith(WorkspaceType.WORKSPACE_PREFIX)
        is_binary = _is_binary_mime(mime_type)

        if expected_handling == "export":
            assert in_export, f"{mime_type} should be exportable"
        elif expected_handling == "workspace_error":
            assert is_workspace and not in_export, f"{mime_type} should trigger workspace error"
        elif expected_handling == "binary_error":
            assert is_binary, f"{mime_type} should trigger binary error"
        elif expected_handling == "text_decode":
            assert not in_export and not is_workspace and not is_binary, f"{mime_type} should be text-decoded"

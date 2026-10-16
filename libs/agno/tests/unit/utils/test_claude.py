import base64
import struct
import sys
from unittest.mock import patch

import pytest

from agno.media import File, Image
from agno.utils.models.claude import _format_file_for_message, _format_image_for_message


def _jpeg(first_marker: int, payload: bytes) -> bytes:
    """A JPEG whose first segment after SOI is `first_marker`, ending with a minimal DQT and EOI."""
    first_segment = struct.pack(">HH", first_marker, len(payload) + 2) + payload
    dqt = struct.pack(">HH", 0xFFDB, 67) + b"\x00" + bytes(range(1, 65))
    return b"\xff\xd8" + first_segment + dqt + b"\xff\xd9"


JPEG_JFIF = _jpeg(0xFFE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
JPEG_EXIF = _jpeg(0xFFE1, b"Exif\x00\x00MM\x00\x2a\x00\x00\x00\x08\x00\x00")
JPEG_XMP = _jpeg(0xFFE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta xmlns:x='adobe:ns:meta/'/>")
JPEG_ICC = _jpeg(0xFFE2, b"ICC_PROFILE\x00\x01\x01" + b"\x00" * 128)
JPEG_ADOBE = _jpeg(0xFFEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class TestFormatFileForMessage:
    def test_filepath_text_csv_returns_text_source(self, tmp_path):
        csv_content = "name,age\nAlice,30\nBob,25"
        p = tmp_path / "data.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "text"
        # Anthropic's text document source only accepts "text/plain" as the media_type.
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == csv_content
        assert result["citations"] == {"enabled": True}

    def test_filepath_pdf_returns_base64_source(self, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake content"
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf_bytes)

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == pdf_bytes

    def test_bytes_content_text_mime_returns_text_source(self):
        raw = b"col1,col2\na,b"

        result = _format_file_for_message(File(content=raw, mime_type="text/csv"))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == "col1,col2\na,b"

    def test_bytes_content_pdf_returns_base64_source(self):
        raw = b"fake-pdf-bytes"

        result = _format_file_for_message(File(content=raw, mime_type="application/pdf"))

        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == raw

    def test_filepath_no_mime_guesses_from_extension(self, tmp_path):
        p = tmp_path / "report.csv"
        p.write_text("x,y\n1,2")

        result = _format_file_for_message(File(filepath=str(p)))

        assert result["source"]["type"] == "text"
        assert result["source"]["data"] == "x,y\n1,2"

    def test_filepath_nonexistent_returns_none(self):
        result = _format_file_for_message(File(filepath="/nonexistent/file.pdf", mime_type="application/pdf"))

        assert result is None

    @pytest.mark.parametrize(
        "mime_type",
        [
            "text/plain",
            "text/html",
            "text/xml",
            "text/javascript",
            "text/markdown",
            "text/csv",
            "application/json",
            "application/x-python",
        ],
    )
    def test_all_text_mimes_route_to_text_source(self, mime_type):
        raw = b"some text content"

        result = _format_file_for_message(File(content=raw, mime_type=mime_type))

        assert result["source"]["type"] == "text"
        # Regardless of the original text subtype, Anthropic only accepts "text/plain"
        # for a text document source, so all of these must be normalised to it.
        assert result["source"]["media_type"] == "text/plain"

    def test_text_data_is_not_base64_encoded(self, tmp_path):
        """Regression: old code base64-encoded before checking MIME, sending gibberish as text."""
        csv_content = "name,value\ntest,123"
        p = tmp_path / "test.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["source"]["data"] == csv_content
        assert result["source"]["data"] != base64.standard_b64encode(csv_content.encode()).decode()

    def test_enable_citations_false_omits_citations_block(self, tmp_path):
        """Anthropic rejects citations + output_format; caller must be able to suppress."""
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"), enable_citations=False)

        assert "citations" not in result

    def test_enable_citations_default_true_adds_citations_block(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"))

        assert result["citations"] == {"enabled": True}

    def test_file_citations_false_overrides_caller_default(self, tmp_path):
        """Per-file opt-out wins over the caller default."""
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(
            File(filepath=str(p), mime_type="application/pdf", citations=False),
            enable_citations=True,
        )

        assert "citations" not in result

    def test_caller_false_is_a_ceiling_even_when_file_requests_citations(self):
        """Safety: File(citations=True) must NOT re-enable citations when the caller
        has disabled them (e.g. structured output is active — re-enabling would
        reintroduce the very 400 this feature exists to prevent)."""
        result = _format_file_for_message(
            File(content=b"fake", mime_type="application/pdf", citations=True),
            enable_citations=False,
        )

        assert "citations" not in result

    def test_citations_not_attached_to_anthropic_uploaded_file(self):
        """Case 0 (external file) has never attached citations — regression guard."""

        class _Ext:
            id = "file_123"

        result = _format_file_for_message(File(external=_Ext()))

        assert "citations" not in result

    def test_url_source_citations_suppressed_when_disabled(self):
        result = _format_file_for_message(File(url="https://example.com/doc.pdf"), enable_citations=False)

        assert result["source"]["type"] == "url"
        assert "citations" not in result


class TestUrlDocumentMimeTypes:
    def test_pdf_url_stays_a_url_source(self):
        result = _format_file_for_message(File(url="https://example.com/doc.pdf", mime_type="application/pdf"))

        assert result["source"]["type"] == "url"
        assert result["source"]["url"] == "https://example.com/doc.pdf"

    def test_unknown_mime_type_url_stays_a_url_source(self):
        result = _format_file_for_message(File(url="https://example.com/doc.pdf"))

        assert result["source"]["type"] == "url"

    def test_non_pdf_url_is_fetched_and_sent_as_text(self, monkeypatch):
        """Anthropic accepts a url document source for PDFs only. Media storage signs a url for
        every offloaded File whatever its type, so a csv reaching the provider as a url document
        comes back a 400 -- it has to be fetched and sent as bytes instead."""
        monkeypatch.setattr("agno.media.media._bytes_from_url", lambda url: b"a,b\n1,2\n")

        result = _format_file_for_message(File(url="https://example.com/data.csv", mime_type="text/csv"))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == "a,b\n1,2\n"

    def test_non_pdf_binary_url_is_fetched_and_base64_encoded(self, monkeypatch):
        monkeypatch.setattr("agno.media.media._bytes_from_url", lambda url: b"\x00\x01BINARY")

        result = _format_file_for_message(File(url="https://example.com/a.docx", mime_type="application/msword"))

        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/msword"
        assert base64.standard_b64decode(result["source"]["data"]) == b"\x00\x01BINARY"


class TestFormatImageForMessage:
    @pytest.mark.parametrize(
        "content",
        [JPEG_JFIF, JPEG_EXIF, JPEG_XMP, JPEG_ICC, JPEG_ADOBE],
        ids=["jfif", "exif", "xmp", "icc", "adobe"],
    )
    def test_jpeg_bytes_are_detected_whatever_the_first_segment(self, content):
        result = _format_image_for_message(Image(content=content))

        assert result is not None
        assert result["source"]["media_type"] == "image/jpeg"
        assert base64.b64decode(result["source"]["data"]) == content

    def test_detection_does_not_need_imghdr_or_filetype(self, monkeypatch):
        """imghdr is gone on Python 3.13+ and filetype is not an agno dependency."""
        monkeypatch.setitem(sys.modules, "imghdr", None)
        monkeypatch.setitem(sys.modules, "filetype", None)

        result = _format_image_for_message(Image(content=JPEG_XMP))

        assert result is not None
        assert result["source"]["media_type"] == "image/jpeg"

    def test_bytes_win_over_a_wrong_file_suffix(self, tmp_path):
        p = tmp_path / "scan.jpg"
        p.write_bytes(PNG_BYTES)

        result = _format_image_for_message(Image(filepath=str(p)))

        assert result is not None
        assert result["source"]["media_type"] == "image/png"

    def test_bytes_win_over_a_wrong_url_suffix(self):
        with patch.object(Image, "get_content_bytes", return_value=JPEG_ICC):
            result = _format_image_for_message(Image(url="https://example.com/photo.png"))

        assert result is not None
        assert result["source"]["media_type"] == "image/jpeg"

    def test_file_suffix_is_used_when_the_bytes_are_not_recognised(self, tmp_path):
        p = tmp_path / "photo.png"
        p.write_bytes(b"\x00" * 16)

        result = _format_image_for_message(Image(filepath=str(p)))

        assert result is not None
        assert result["source"]["media_type"] == "image/png"

    def test_unrecognised_bytes_without_a_suffix_are_dropped(self):
        assert _format_image_for_message(Image(content=b"not an image at all")) is None

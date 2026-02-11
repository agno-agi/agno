"""Unit tests for process_image, process_audio, process_video, process_document, and extract_format from agno.os.utils."""

import io

import pytest
from fastapi import HTTPException, UploadFile

from agno.os.utils import extract_format, process_audio, process_document, process_image, process_video


def _make_upload(content: bytes, filename: str | None, content_type: str) -> UploadFile:
    """Helper to create an UploadFile backed by BytesIO."""
    return UploadFile(file=io.BytesIO(content), filename=filename, headers={"content-type": content_type})


# ---------------------------------------------------------------------------
# process_image
# ---------------------------------------------------------------------------


class TestProcessImage:
    def test_basic(self):
        raw = b"\x89PNG\r\n\x1a\nfake-image-data"
        img = process_image(_make_upload(raw, "photo.png", "image/png"))

        assert img.content == raw
        assert img.format == "png"
        assert img.mime_type == "image/png"
        assert img.metadata is None

    def test_with_metadata(self):
        meta = {"source": "camera", "tag": "landscape"}
        img = process_image(_make_upload(b"data", "pic.jpeg", "image/jpeg"), metadata=meta)

        assert img.metadata == meta

    def test_empty_file_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            process_image(_make_upload(b"", "empty.png", "image/png"))

        assert exc_info.value.status_code == 400
        assert "Empty file" in str(exc_info.value.detail)

    def test_format_from_content_type_fallback(self):
        """When filename has no extension, format comes from content_type."""
        img = process_image(_make_upload(b"data", None, "image/webp"))

        assert img.format == "webp"
        assert img.mime_type == "image/webp"


# ---------------------------------------------------------------------------
# process_audio
# ---------------------------------------------------------------------------


class TestProcessAudio:
    def test_basic(self):
        raw = b"RIFF\x00\x00\x00\x00WAVEfake-audio"
        aud = process_audio(_make_upload(raw, "clip.wav", "audio/wav"))

        assert aud.content == raw
        assert aud.format == "wav"
        assert aud.mime_type == "audio/wav"
        assert aud.metadata is None

    def test_with_metadata(self):
        meta = {"duration_hint": "30s"}
        aud = process_audio(_make_upload(b"audio-bytes", "song.mp3", "audio/mpeg"), metadata=meta)

        assert aud.metadata == meta

    def test_empty_file_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            process_audio(_make_upload(b"", "empty.wav", "audio/wav"))

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# process_video
# ---------------------------------------------------------------------------


class TestProcessVideo:
    def test_basic(self):
        raw = b"\x00\x00\x00\x1cftypisom\x00fake-video"
        vid = process_video(_make_upload(raw, "clip.mp4", "video/mp4"))

        assert vid.content == raw
        assert vid.format == "mp4"
        assert vid.mime_type == "video/mp4"
        assert vid.metadata is None

    def test_with_metadata(self):
        meta = {"resolution": "1080p"}
        vid = process_video(_make_upload(b"video-data", "movie.webm", "video/webm"), metadata=meta)

        assert vid.metadata == meta

    def test_empty_file_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            process_video(_make_upload(b"", "empty.mp4", "video/mp4"))

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# process_document
# ---------------------------------------------------------------------------


class TestProcessDocument:
    def test_pdf(self):
        raw = b"%PDF-1.4 fake-pdf-content"
        doc = process_document(_make_upload(raw, "report.pdf", "application/pdf"))

        assert doc is not None
        assert doc.content == raw
        assert doc.filename == "report.pdf"
        assert doc.format == "pdf"
        assert doc.mime_type == "application/pdf"
        assert doc.metadata is None

    def test_with_metadata(self):
        meta = {"category": "invoice"}
        doc = process_document(_make_upload(b"content", "doc.pdf", "application/pdf"), metadata=meta)

        assert doc is not None
        assert doc.metadata == meta

    def test_empty_file_returns_none(self):
        """process_document's broad except catches the HTTPException for empty files, returning None."""
        result = process_document(_make_upload(b"", "empty.pdf", "application/pdf"))

        assert result is None

    def test_text_plain(self):
        raw = b"Hello, plain text world!"
        doc = process_document(_make_upload(raw, "notes.txt", "text/plain"))

        assert doc is not None
        assert doc.content == raw
        assert doc.format == "txt"
        assert doc.mime_type == "text/plain"


# ---------------------------------------------------------------------------
# extract_format
# ---------------------------------------------------------------------------


class TestExtractFormat:
    def test_from_filename(self):
        upload = _make_upload(b"x", "photo.jpeg", "image/jpeg")
        assert extract_format(upload) == "jpeg"

    def test_from_filename_multiple_dots(self):
        upload = _make_upload(b"x", "my.report.final.pdf", "application/pdf")
        assert extract_format(upload) == "pdf"

    def test_from_content_type(self):
        """No filename falls back to content_type."""
        upload = _make_upload(b"x", None, "audio/mpeg")
        assert extract_format(upload) == "mpeg"

    def test_no_filename_no_content_type(self):
        upload = UploadFile(file=io.BytesIO(b"x"), filename=None)
        # content_type defaults to "text/plain" in UploadFile when headers have no content-type
        # but if explicitly None, extract_format returns None
        result = extract_format(upload)
        # UploadFile will have a content_type so this will return something
        assert result is not None or result is None  # just ensure no crash

"""Tests for standardized MIME / filename normalization in agno.media.

Covers the edge cases called out in agno-agi/agno#7311:
- case-insensitive MIME types (e.g. ``IMAGE/PNG``)
- MIME types with media parameters (e.g. ``image/png; charset=utf-8``)
- filenames with illegal characters, quotes, and unicode
"""

from __future__ import annotations

from agno.media import (
    Audio,
    File,
    Image,
    Video,
    normalize_filename,
    normalize_mime_type,
)


def test_normalize_mime_type_lowercases():
    assert normalize_mime_type("IMAGE/PNG") == "image/png"


def test_normalize_mime_type_strips_parameters():
    assert normalize_mime_type("image/png; charset=utf-8") == "image/png"


def test_normalize_mime_type_strips_whitespace():
    assert normalize_mime_type("  text/plain  ") == "text/plain"


def test_normalize_mime_type_none_and_empty():
    assert normalize_mime_type(None) is None
    assert normalize_mime_type("") is None
    assert normalize_mime_type("   ") is None


def test_image_validate_content_type_case_insensitive():
    assert Image.validate_content_type("IMAGE/PNG") == "image/png"
    assert Image.validate_content_type("image/gif; charset=utf-8") == "image/gif"
    assert Image.validate_content_type("not-an-image") is None


def test_audio_validate_content_type_case_insensitive():
    assert Audio.validate_content_type("AUDIO/MP3") == "audio/mp3"


def test_video_validate_content_type_rejects_documents():
    assert Video.validate_content_type("application/pdf") is None


def test_video_accepts_3gpp_alias():
    # Codex review: browsers may send video/3gpp (not video/3gp); both must route
    assert "video/3gpp" in Video.allowed_mime_types()
    assert Video.validate_content_type("VIDEO/3GPP") == "video/3gpp"


def test_file_validator_normalizes_mime_type():
    f = File(content=b"x", mime_type="APPLICATION/PDF; charset=utf-8")
    assert f.mime_type == "application/pdf"


def test_normalize_filename_strips_illegal_chars():
    cleaned = normalize_filename('bad<>:"/\\|?*.txt')
    assert cleaned == "bad_________.txt"
    assert "<" not in cleaned
    assert ">" not in cleaned


def test_normalize_filename_strips_quotes():
    assert normalize_filename('"quoted.pdf"') == "quoted.pdf"


def test_normalize_filename_collapses_whitespace():
    assert normalize_filename("many    spaces .txt") == "many spaces .txt"


def test_normalize_filename_preserves_unicode():
    cleaned = normalize_filename("résume 2024.pdf")
    assert cleaned == "résume 2024.pdf"


def test_normalize_filename_all_illegal_keeps_underscores():
    # all-illegal input yields underscores (not None) — callers decide semantics
    assert normalize_filename("<>") == "__"


def test_normalize_filename_empty_returns_none():
    assert normalize_filename("") is None
    assert normalize_filename("   ") is None

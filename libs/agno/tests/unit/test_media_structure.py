from pathlib import Path

import pytest

from agno.media import Audio, File, Image, Video


def test_image_valid_mime_types():
    # Success cases with standard and new (SVG) types
    assert Image(url="http://example.com/i.png", mime_type="image/png")
    assert Image(content=b"fake", mime_type="image/svg+xml")
    assert Image(filepath="test.jpg", mime_type="image/jpeg")


def test_image_invalid_mime_type_raises_error():
    with pytest.raises(ValueError, match="Invalid MIME type"):
        Image(url="http://example.com/i.png", mime_type="application/pdf")


def test_image_source_validation():
    # Success: exactly one source provided
    assert Image(url="http://example.com/i.png")
    assert Image(content=b"bytes")
    assert Image(filepath=Path("test.png"))

    # Error: no source provided
    with pytest.raises(ValueError, match="One of 'url', 'filepath', or 'content' must be provided"):
        Image(id="123")

    # Error: multiple sources provided
    with pytest.raises(ValueError, match="Only one of 'url', 'filepath', or 'content' should be provided"):
        Image(url="http://x.com", content=b"bytes")


def test_audio_validation():
    assert Audio(url="http://ex.com/a.mp3", mime_type="audio/mpeg")
    with pytest.raises(ValueError, match="Invalid MIME type"):
        Audio(url="http://ex.com/a.mp3", mime_type="video/mp4")


def test_video_validation():
    assert Video(url="http://ex.com/v.mp4", mime_type="video/mp4")
    assert Video(url="http://ex.com/v.ogg", mime_type="video/ogg")
    with pytest.raises(ValueError, match="Invalid MIME type"):
        Video(url="http://ex.com/v.mp4", mime_type="image/png")


def test_file_validation_and_organization():
    # Success with new types (ZIP, YAML, Office)
    assert File(content=b"data", mime_type="application/zip")
    assert File(content=b"data", mime_type="text/yaml")
    assert File(content=b"data", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    # Verification of organized metadata fields
    f = File(content=b"x", filename="doc.pdf", size=1024, format="pdf")
    assert f.filename == "doc.pdf"
    assert f.size == 1024

    with pytest.raises(ValueError, match="Invalid MIME type"):
        File(content=b"x", mime_type="application/octet-stream")


def test_auto_id_generation():
    img = Image(url="http://example.com/i.png")
    assert img.id is not None
    assert len(img.id) > 10  # Should be a UUIDv4 string


def test_media_case_insensitivity_normalization():
    # Test that uppercase MIME types are normalized to lowercase
    img = Image(content=b"x", mime_type="IMAGE/PNG")
    assert img.mime_type == "image/png"

    svg = Image(content=b"<svg/>", mime_type="image/Svg+Xml")
    assert svg.mime_type == "image/svg+xml"


def test_file_special_characters_name():
    # Test that special characters in filenames don't break the model
    special_name = "currículo_2024_🚀.pdf"
    f = File(content=b"x", filename=special_name)
    assert f.filename == special_name

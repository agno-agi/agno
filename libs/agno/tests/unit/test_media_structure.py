from pathlib import Path

import pytest

from agno.media import Audio, File, Image, Video


def test_image_accepts_valid_mime_types():
    assert Image(url="http://example.com/i.png", mime_type="image/png")
    assert Image(content=b"fake", mime_type="image/svg+xml")
    assert Image(filepath="test.jpg", mime_type="image/jpeg")


def test_image_source_validation():
    assert Image(url="http://example.com/i.png")
    assert Image(content=b"bytes")
    assert Image(filepath=Path("test.png"))

    with pytest.raises(ValueError, match="One of 'url', 'filepath', or 'content' must be provided"):
        Image(id="123")

    with pytest.raises(ValueError, match="Only one of 'url', 'filepath', or 'content' should be provided"):
        Image(url="http://x.com", content=b"bytes")


def test_audio_accepts_valid_mime_types():
    assert Audio(url="http://ex.com/a.mp3", mime_type="audio/mpeg")
    assert Audio(url="http://ex.com/a.wav", mime_type="audio/wav")


def test_video_accepts_valid_mime_types():
    assert Video(url="http://ex.com/v.mp4", mime_type="video/mp4")
    assert Video(url="http://ex.com/v.webm", mime_type="video/webm")


def test_file_validate_mime_type():
    assert File(content=b"data", mime_type="application/zip")
    assert File(content=b"data", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert File(content=b"data", mime_type="application/vnd.ms-excel")
    assert File(content=b"data", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert File(content=b"data", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")

    f = File(content=b"x", filename="doc.pdf", size=1024, format="pdf")
    assert f.filename == "doc.pdf"
    assert f.size == 1024

    with pytest.raises(ValueError, match="Invalid MIME type"):
        File(content=b"x", mime_type="application/octet-stream")


def test_file_validate_mime_type_normalizes_case():
    f = File(content=b"x", mime_type="APPLICATION/PDF")
    assert f.mime_type == "application/pdf"


def test_auto_id_generation():
    img = Image(url="http://example.com/i.png")
    assert img.id is not None
    assert len(img.id) > 10


def test_file_special_characters_name():
    special_name = "currículo_2024.pdf"
    f = File(content=b"x", filename=special_name)
    assert f.filename == special_name


def test_valid_mime_types_coverage():
    assert "image/svg+xml" in Image.valid_mime_types()
    assert "audio/flac" in Audio.valid_mime_types()
    assert "video/quicktime" in Video.valid_mime_types()
    assert "application/zip" in File.valid_mime_types()
    assert not any(m.startswith("image/") for m in File.valid_mime_types())
    assert not any(m.startswith("audio/") for m in File.valid_mime_types())
    assert not any(m.startswith("video/") for m in File.valid_mime_types())

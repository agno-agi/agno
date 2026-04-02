from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.utils import extract_format, process_audio, process_document, process_image, process_video


def test_extract_format_from_filename():
    # Success cases from extension
    file1 = UploadFile(BytesIO(b""), filename="test.png")
    assert extract_format(file1) == "png"

    file2 = UploadFile(BytesIO(b""), filename="data.YAML")
    assert extract_format(file2) == "yaml"

    # Success case from content type fallback
    headers = Headers({"content-type": "image/jpeg"})
    file3 = UploadFile(BytesIO(b""), filename=None, headers=headers)
    assert extract_format(file3) == "jpg"


def test_process_image_success():
    content = b"fake image bytes"
    headers = Headers({"content-type": "image/jpeg"})
    file = UploadFile(BytesIO(content), filename="test.jpg", headers=headers)

    img = process_image(file)
    assert isinstance(img, Image)
    assert img.content == content
    assert img.mime_type == "image/jpeg"
    assert img.format == "jpg"


def test_process_image_empty_raises_error():
    headers = Headers({"content-type": "image/jpeg"})
    file = UploadFile(BytesIO(b""), filename="test.jpg", headers=headers)
    with pytest.raises(HTTPException) as exc:
        process_image(file)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Empty file"


def test_process_document_success():
    content = b"key: value"
    headers = Headers({"content-type": "text/yaml"})
    file = UploadFile(BytesIO(content), filename="config.yaml", headers=headers)

    doc = process_document(file)
    assert isinstance(doc, FileMedia)
    assert doc.content == content
    assert doc.filename == "config.yaml"
    assert doc.mime_type == "text/yaml"


def test_process_audio_and_video():
    # Audio
    h_audio = Headers({"content-type": "audio/mpeg"})
    audio_file = UploadFile(BytesIO(b"audio"), filename="a.mp3", headers=h_audio)
    assert isinstance(process_audio(audio_file), Audio)

    # Video
    h_video = Headers({"content-type": "video/mp4"})
    video_file = UploadFile(BytesIO(b"video"), filename="v.mp4", headers=h_video)
    assert isinstance(process_video(video_file), Video)


def test_extract_format_hardened_edge_cases():
    # Double extension attack: should take the ACTUAL final extension
    file1 = UploadFile(BytesIO(b""), filename="scam.png.exe")
    assert extract_format(file1) == "exe"

    # Complex Content-Type header with params
    headers2 = Headers({"content-type": "image/png; charset=utf-8; profile=standard"})
    file2 = UploadFile(BytesIO(b""), filename="test", headers=headers2)
    assert extract_format(file2) == "png"

    # Multiple dots in filename
    file3 = UploadFile(BytesIO(b""), filename="backup.2024.03.31.ZIP")
    assert extract_format(file3) == "zip"

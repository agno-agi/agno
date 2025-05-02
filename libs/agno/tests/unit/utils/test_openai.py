##test

import base64
import os
from pathlib import Path

import pytest

from agno.media import Audio, File, Image
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message


# Helper function to create dummy file
def create_dummy_file(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


# --- Audio Fixtures --- #
@pytest.fixture
def dummy_audio_bytes() -> bytes:
    # Create simple dummy WAV-like bytes (not a real WAV header)
    return (
        b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        + os.urandom(100)
    )


@pytest.fixture
def tmp_wav_file(tmp_path: Path, dummy_audio_bytes: bytes) -> Path:
    file_path = tmp_path / "test_audio.wav"
    create_dummy_file(file_path, dummy_audio_bytes)
    return file_path


@pytest.fixture
def tmp_mp3_file(tmp_path: Path, dummy_audio_bytes: bytes) -> Path:
    # Use same dummy bytes, different extension for testing format guessing
    file_path = tmp_path / "test_audio.mp3"
    create_dummy_file(file_path, dummy_audio_bytes)
    return file_path


@pytest.fixture
def tmp_m4a_file(tmp_path: Path, dummy_audio_bytes: bytes) -> Path:
    file_path = tmp_path / "test_audio.m4a"
    create_dummy_file(file_path, dummy_audio_bytes)
    return file_path


@pytest.fixture
def tmp_flac_file(tmp_path: Path, dummy_audio_bytes: bytes) -> Path:
    file_path = tmp_path / "test_audio.flac"
    create_dummy_file(file_path, dummy_audio_bytes)
    return file_path


# --- Image Fixtures --- #
@pytest.fixture
def dummy_image_bytes() -> bytes:
    # Create simple dummy PNG-like bytes (not a real PNG)
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        + os.urandom(20)
    )


@pytest.fixture
def tmp_png_file(tmp_path: Path, dummy_image_bytes: bytes) -> Path:
    file_path = tmp_path / "test_image.png"
    create_dummy_file(file_path, dummy_image_bytes)
    return file_path


@pytest.fixture
def tmp_jpeg_file(tmp_path: Path, dummy_image_bytes: bytes) -> Path:
    file_path = tmp_path / "test_image.jpeg"
    create_dummy_file(file_path, dummy_image_bytes)
    return file_path


@pytest.fixture
def tmp_webp_file(tmp_path: Path, dummy_image_bytes: bytes) -> Path:
    file_path = tmp_path / "test_image.webp"
    create_dummy_file(file_path, dummy_image_bytes)
    return file_path


# --- Tests for audio_to_message ---


def test_audio_to_message_empty():
    """Test audio_to_message with an empty list."""
    assert audio_to_message([]) == []


def test_audio_to_message_bytes(dummy_audio_bytes):
    """Test audio_to_message with raw bytes content."""
    audio = [Audio(content=dummy_audio_bytes, format="wav")]
    result = audio_to_message(audio)
    assert len(result) == 1
    msg = result[0]
    assert msg["type"] == "input_audio"
    assert msg["input_audio"]["format"] == "wav"
    assert base64.b64decode(msg["input_audio"]["data"]) == dummy_audio_bytes


def test_audio_to_message_bytes_no_format(dummy_audio_bytes):
    """Test audio_to_message with raw bytes and default format."""
    audio = [Audio(content=dummy_audio_bytes)]  # Format defaults to wav
    result = audio_to_message(audio)
    assert len(result) == 1
    assert result[0]["input_audio"]["format"] == "wav"
    assert base64.b64decode(result[0]["input_audio"]["data"]) == dummy_audio_bytes


@pytest.mark.parametrize(
    "file_fixture_name, expected_format",
    [
        ("tmp_wav_file", "wav"),
        ("tmp_mp3_file", "mp3"),
        ("tmp_m4a_file", "m4a"),
        ("tmp_flac_file", "flac"),
    ],
)
def test_audio_to_message_filepath_formats(file_fixture_name, expected_format, request, dummy_audio_bytes):
    """Test audio_to_message with various valid file path formats."""
    tmp_file = request.getfixturevalue(file_fixture_name)
    audio = [Audio(filepath=str(tmp_file))]
    result = audio_to_message(audio)
    assert len(result) == 1
    msg = result[0]
    assert msg["type"] == "input_audio"
    assert msg["input_audio"]["format"] == expected_format  # Guessed from extension
    assert base64.b64decode(msg["input_audio"]["data"]) == dummy_audio_bytes


def test_audio_to_message_filepath_override_format(tmp_mp3_file, dummy_audio_bytes):
    """Test audio_to_message with a file path and explicit format override."""
    # Use mp3 extension but explicitly provide format wav
    audio = [Audio(filepath=tmp_mp3_file, format="wav")]
    result = audio_to_message(audio)
    assert len(result) == 1
    assert result[0]["input_audio"]["format"] == "wav"
    assert base64.b64decode(result[0]["input_audio"]["data"]) == dummy_audio_bytes


def test_audio_to_message_filepath_not_found(tmp_path):
    """Test audio_to_message with a non-existent file path."""
    audio = [Audio(filepath=str(tmp_path / "nonexistent.wav"))]
    result = audio_to_message(audio)
    assert result == []  # Should log error and skip


def test_audio_to_message_filepath_is_dir(tmp_path):
    """Test audio_to_message with a path that is a directory."""
    (tmp_path / "a_directory").mkdir()
    audio = [Audio(filepath=str(tmp_path / "a_directory"))]
    result = audio_to_message(audio)
    assert result == []  # Should log error and skip


@pytest.mark.parametrize(
    "url, expected_format",
    [
        ("http://example.com/audio.mp3", "mp3"),
        ("https://cdn.test/track.wav?token=abc", "wav"),
        ("http://another.site/file.m4a", "m4a"),
    ],
)
def test_audio_to_message_url(url, expected_format, mocker):
    """Test audio_to_message with various URL formats (mocking content fetch)."""
    mock_content = b"mocked_audio_content_for_" + url.encode()
    mock_audio = Audio(url=url)
    # Mock the property that fetches URL content
    mocker.patch.object(Audio, "audio_url_content", new_callable=mocker.PropertyMock, return_value=mock_content)

    result = audio_to_message([mock_audio])
    assert len(result) == 1
    msg = result[0]
    assert msg["type"] == "input_audio"
    assert msg["input_audio"]["format"] == expected_format  # Guessed from URL
    assert base64.b64decode(msg["input_audio"]["data"]) == mock_content


def test_audio_to_message_url_no_fetch(mocker):
    """Test audio_to_message when URL fetch returns None."""
    mock_audio = Audio(url="http://example.com/bad_audio.wav")
    mocker.patch.object(Audio, "audio_url_content", new_callable=mocker.PropertyMock, return_value=None)
    result = audio_to_message([mock_audio])
    assert result == []  # Should skip if content is None


def test_audio_to_message_mixed(tmp_wav_file, dummy_audio_bytes, mocker):
    """Test audio_to_message with a mix of valid and invalid inputs."""
    mock_content = b"more_mock_audio"
    # Configure mock to return content first time, None second time for the same object if needed,
    # but here we use different objects anyway. Patching the class affects all instances.
    mock_prop = mocker.patch.object(Audio, "audio_url_content", new_callable=mocker.PropertyMock)
    mock_prop.side_effect = [mock_content, None]  # Define side effects for consecutive calls

    audios = [
        Audio(content=dummy_audio_bytes),  # Valid bytes
        Audio(filepath=str(tmp_wav_file)),  # Valid file
        Audio(filepath="/non/existent/path.wav"),  # Invalid file
        Audio(url="http://example.com/good.aac"),  # Valid URL (first call to property)
        Audio(url="http://example.com/fails.mp3"),  # Invalid URL (second call to property)
    ]
    result = audio_to_message(audios)
    assert len(result) == 3  # Should skip the two invalid ones
    assert result[0]["input_audio"]["format"] == "wav"
    assert result[1]["input_audio"]["format"] == "wav"
    assert result[2]["input_audio"]["format"] == "aac"


# --- Tests for images_to_message ---


def test_images_to_message_empty():
    """Test images_to_message with an empty list."""
    assert images_to_message([]) == []


def test_images_to_message_bytes(dummy_image_bytes):
    """Test images_to_message with raw bytes content (defaults to jpeg)."""
    images = [Image(content=dummy_image_bytes)]
    result = images_to_message(images)
    assert len(result) == 1
    msg = result[0]
    assert msg["type"] == "image_url"
    assert msg["image_url"]["url"].startswith("data:image/jpeg;base64,")  # Default MIME
    assert base64.b64decode(msg["image_url"]["url"].split(",")[1]) == dummy_image_bytes


@pytest.mark.parametrize(
    "file_fixture_name, expected_mime",
    [
        ("tmp_png_file", "image/png"),
        ("tmp_jpeg_file", "image/jpeg"),
        ("tmp_webp_file", "image/webp"),
    ],
)
def test_images_to_message_filepath_formats(file_fixture_name, expected_mime, request, dummy_image_bytes):
    """Test images_to_message with various valid file path formats."""
    tmp_file = request.getfixturevalue(file_fixture_name)
    images = [Image(filepath=str(tmp_file))]
    result = images_to_message(images)
    assert len(result) == 1
    msg = result[0]
    assert msg["type"] == "image_url"
    assert msg["image_url"]["url"].startswith(f"data:{expected_mime};base64,")
    assert base64.b64decode(msg["image_url"]["url"].split(",")[1]) == dummy_image_bytes


def test_images_to_message_filepath_not_found(tmp_path):
    """Test images_to_message with a non-existent file path."""
    images = [Image(filepath=str(tmp_path / "nonexistent.png"))]
    result = images_to_message(images)
    assert result == []  # _process_image should return None


def test_images_to_message_filepath_is_dir(tmp_path):
    """Test images_to_message with a path that is a directory."""
    (tmp_path / "img_dir").mkdir()
    images = [Image(filepath=str(tmp_path / "img_dir"))]
    result = images_to_message(images)
    assert result == []  # _process_image should return None


def test_images_to_message_url_data_uri():
    """Test images_to_message with a data URI."""
    data_uri = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    images = [Image(url=data_uri)]
    result = images_to_message(images)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"] == data_uri


def test_images_to_message_url_http():
    """Test images_to_message with an HTTP/S URL."""
    http_url = "https://example.com/image.jpg"
    images = [Image(url=http_url)]
    result = images_to_message(images)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"] == http_url


def test_images_to_message_url_invalid_prefix():
    """Test images_to_message with an invalid URL prefix."""
    invalid_url = "ftp://example.com/image.png"
    images = [Image(url=invalid_url)]
    result = images_to_message(images)
    # _process_image_url raises ValueError, _process_image catches it, logs, returns None
    assert result == []


@pytest.mark.parametrize("detail_value", ["low", "high", "auto", None])
def test_images_to_message_with_detail(detail_value, dummy_image_bytes):
    """Test images_to_message including the detail parameter."""
    images = [Image(content=dummy_image_bytes, detail=detail_value)]
    result = images_to_message(images)
    assert len(result) == 1
    if detail_value:
        assert result[0]["image_url"]["detail"] == detail_value
    else:
        # If detail is None, the key should not be present
        assert "detail" not in result[0]["image_url"]


def test_images_to_message_mixed(tmp_png_file, dummy_image_bytes):
    """Test images_to_message with a mix of valid and invalid inputs."""
    images = [
        Image(content=dummy_image_bytes),  # Valid bytes (jpeg default)
        Image(filepath=str(tmp_png_file)),  # Valid file (png)
        Image(url="https://example.com/image.webp"),  # Valid URL
        Image(filepath="/non/existent/path.jpg"),  # Invalid file
        Image(url="ftp://invalid.url"),  # Invalid URL
    ]
    result = images_to_message(images)
    assert len(result) == 3  # Should skip the two invalid ones
    assert result[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert result[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result[2]["image_url"]["url"] == "https://example.com/image.webp"


# --- Tests for _format_file_for_message --- #
def test_format_file_external():
    f = File(external="file123")
    msg = _format_file_for_message(f)
    # External-file branch was removed, unsupported externals return None
    assert msg is None


def test_format_file_url_inline(mocker):
    f = File(url="http://example.com/doc.pdf")
    mock_data = (b"PDF_CONTENT", "application/pdf")
    mocker.patch.object(File, "file_url_content", new_callable=mocker.PropertyMock, return_value=mock_data)
    msg = _format_file_for_message(f)
    assert msg["type"] == "file"
    assert msg["file"]["filename"] == "doc.pdf"
    data_url = msg["file"]["file_data"]
    assert data_url.startswith("data:application/pdf;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == mock_data[0]


def test_format_file_path_inline(tmp_path):
    content = b"HELLO"
    p = tmp_path / "test.txt"
    p.write_bytes(content)
    f = File(filepath=str(p))
    msg = _format_file_for_message(f)
    assert msg["type"] == "file"
    assert msg["file"]["filename"] == "test.txt"
    data_url = msg["file"]["file_data"]
    assert data_url.startswith("data:text/plain;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == content


def test_format_file_path_persistent(tmp_path):
    # Large files are inlined under the same logic
    content = b"PERSIST"
    p = tmp_path / "big.bin"
    p.write_bytes(content)
    f = File(filepath=str(p))
    msg = _format_file_for_message(f)
    assert msg["type"] == "file"
    assert msg["file"]["filename"] == "big.bin"
    data_url = msg["file"]["file_data"]
    # It should be a data URL with base64 payload
    assert data_url.startswith("data:")
    assert ";base64," in data_url
    # The base64 payload should decode back to the original content
    payload = data_url.split(",", 1)[1]
    assert base64.b64decode(payload) == content


def test_format_file_raw_bytes():
    content = b"RAWBYTES"
    f = File(content=content)
    msg = _format_file_for_message(f)
    assert msg["type"] == "file"
    assert msg["file"]["filename"] == "file"
    data_url = msg["file"]["file_data"]
    assert data_url.startswith("data:application/pdf;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == content

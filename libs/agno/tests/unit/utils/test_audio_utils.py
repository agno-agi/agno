import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.utils.audio import write_audio_to_file


def test_write_audio_to_file_basic():
    """Test basic audio file writing functionality."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_with_directory_creation():
    """Test audio file writing with directory creation."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    # Create a temporary directory path that doesn't exist
    with tempfile.TemporaryDirectory() as temp_dir:
        subdir = os.path.join(temp_dir, "audio", "subdir")
        filename = os.path.join(subdir, "test_audio.wav")

        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the directory was created and file was written
        assert os.path.exists(subdir)
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data


def test_write_audio_to_file_existing_directory():
    """Test audio file writing to existing directory."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = os.path.join(temp_dir, "test_audio.wav")

        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data


def test_write_audio_to_file_empty_audio():
    """Test writing empty audio data."""
    # Create empty audio data
    test_audio_data = b""
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and is empty
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == b""
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_large_audio():
    """Test writing large audio data."""
    # Create large test audio data (1MB)
    test_audio_data = b"x" * (1024 * 1024)
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data
        assert len(written_data) == 1024 * 1024
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_special_characters_in_filename():
    """Test writing audio file with special characters in filename."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create filename with special characters
        filename = os.path.join(temp_dir, "test-audio_123.wav")

        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data


def test_write_audio_to_file_unicode_filename():
    """Test writing audio file with unicode characters in filename."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create filename with unicode characters
        filename = os.path.join(temp_dir, "test_audio_🎵.wav")

        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data


@patch("agno.utils.audio.log_info")
def test_write_audio_to_file_logging(mock_log_info):
    """Test that logging is called correctly."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify logging was called with the correct message
        mock_log_info.assert_called_once_with(f"Audio file saved to {filename}")
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_overwrite_existing():
    """Test overwriting an existing audio file."""
    # Create test audio data
    test_audio_data = b"new audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name
        # Write some initial content
        temp_file.write(b"old content")

    try:
        # Call the function to overwrite the file
        write_audio_to_file(base64_audio, filename)

        # Verify the file was overwritten with new content
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data
        assert written_data != b"old content"
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_pathlib_path():
    """Test writing audio file using pathlib.Path object."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = Path(temp_dir) / "test_audio.wav"

        # Call the function
        write_audio_to_file(base64_audio, str(filename))

        # Verify the file was created and contains the correct data
        assert filename.exists()
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data


def test_write_audio_to_file_relative_path():
    """Test writing audio file using relative path."""
    # Create test audio data
    test_audio_data = b"test audio content"
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    # Use a relative path
    filename = "test_audio_relative.wav"

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and contains the correct data
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == test_audio_data
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_invalid_base64():
    """Test writing audio file with invalid base64 data."""
    # Create invalid base64 data
    invalid_base64 = "invalid_base64_data!"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # This should raise a binascii.Error
        with pytest.raises(Exception):
            write_audio_to_file(invalid_base64, filename)
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_none_audio():
    """Test writing None audio data."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # This should raise a TypeError
        with pytest.raises(TypeError):
            write_audio_to_file(None, filename)
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)


def test_write_audio_to_file_empty_string_audio():
    """Test writing empty string audio data."""
    # Create test audio data
    test_audio_data = b""
    base64_audio = base64.b64encode(test_audio_data).decode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        filename = temp_file.name

    try:
        # Call the function
        write_audio_to_file(base64_audio, filename)

        # Verify the file was created and is empty
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            written_data = f.read()
        assert written_data == b""
    finally:
        # Cleanup
        if os.path.exists(filename):
            os.unlink(filename)

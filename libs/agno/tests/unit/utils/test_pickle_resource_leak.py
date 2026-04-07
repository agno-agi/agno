"""Tests for file handle management in pickle utilities."""

import pickle
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from agno.utils.pickle import pickle_object_to_file, unpickle_object_from_file


class TestPickleObjectToFile:
    """Test that pickle_object_to_file properly closes file handles."""

    def test_file_handle_closed_after_write(self, tmp_path: Path):
        """Verify the file handle is closed after pickling."""
        file_path = tmp_path / "test.pkl"
        obj = {"key": "value", "number": 42}

        pickle_object_to_file(obj, file_path)

        # Verify the file was written correctly (implying proper open/close)
        with file_path.open("rb") as f:
            loaded = pickle.load(f)
        assert loaded == obj

    def test_creates_parent_directories(self, tmp_path: Path):
        """Verify parent directories are created."""
        file_path = tmp_path / "sub" / "dir" / "test.pkl"
        obj = [1, 2, 3]

        pickle_object_to_file(obj, file_path)

        assert file_path.exists()
        with file_path.open("rb") as f:
            assert pickle.load(f) == obj


class TestUnpickleObjectFromFile:
    """Test that unpickle_object_from_file properly closes file handles."""

    def test_file_handle_closed_after_read(self, tmp_path: Path):
        """Verify the file handle is closed after unpickling."""
        file_path = tmp_path / "test.pkl"
        obj = {"key": "value"}

        with file_path.open("wb") as f:
            pickle.dump(obj, f)

        result = unpickle_object_from_file(file_path)
        assert result == obj

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        """Verify None is returned when file doesn't exist."""
        file_path = tmp_path / "nonexistent.pkl"
        result = unpickle_object_from_file(file_path)
        assert result is None

    def test_verify_class_mismatch_returns_none(self, tmp_path: Path):
        """Verify None is returned when class doesn't match."""
        file_path = tmp_path / "test.pkl"
        with file_path.open("wb") as f:
            pickle.dump({"key": "value"}, f)

        result = unpickle_object_from_file(file_path, verify_class=list)
        assert result is None

    def test_verify_class_match_returns_object(self, tmp_path: Path):
        """Verify object is returned when class matches."""
        file_path = tmp_path / "test.pkl"
        obj = [1, 2, 3]
        with file_path.open("wb") as f:
            pickle.dump(obj, f)

        result = unpickle_object_from_file(file_path, verify_class=list)
        assert result == obj

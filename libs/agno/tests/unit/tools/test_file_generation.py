"""Tests for FileGenerationTools security and edge-case handling."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.exceptions import FileGenerationSecurityError
from agno.tools.file_generation import FileGenerationTools


def test_relative_traversal_blocked():
    """Relative-traversal filenames must be stripped to bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "../../../escape.json")
        assert (Path(tmp_dir) / "escape.json").exists()
        assert not (Path(tmp_dir).parent / "escape.json").exists()


def test_absolute_path_blocked():
    """Absolute-path filenames must be stripped to bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "/tmp/test_absolute_xyz_unique.json")
        assert (Path(tmp_dir) / "test_absolute_xyz_unique.json").exists()
        assert not Path("/tmp/test_absolute_xyz_unique.json").exists()


def test_nested_path_stripped():
    """Nested-path filenames must be flattened to the bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "subdir/file.json")
        assert (Path(tmp_dir) / "file.json").exists()
        assert not (Path(tmp_dir) / "subdir").exists()


def test_normal_filename_unchanged():
    """Normal filenames should pass through unchanged."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "report.json")
        assert (Path(tmp_dir) / "report.json").exists()


def test_filename_with_dots_in_name():
    """Filenames with dots in the middle are valid and must be preserved intact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "q1.report.json")
        assert (Path(tmp_dir) / "q1.report.json").exists()


def test_empty_filename_raises():
    """Empty filename must raise FileGenerationSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(FileGenerationSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "")


def test_dot_filename_raises():
    """Filename '.' must raise FileGenerationSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(FileGenerationSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", ".")


def test_dotdot_filename_raises():
    """Filename '..' must raise FileGenerationSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(FileGenerationSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "..")


def test_only_traversal_raises():
    """Filename '../' (path-only) must raise FileGenerationSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(FileGenerationSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "../")


def test_security_violation_logs_warning():
    """Security violations should emit a warning log for ops visibility."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with patch("agno.tools.file_generation.log_warning") as mock_log_warning:
            with pytest.raises(FileGenerationSecurityError):
                tool._save_file_to_disk("payload", "..")
        mock_log_warning.assert_called_once()
        assert "Security violation" in str(mock_log_warning.call_args)


def test_no_output_directory_returns_none_filepath():
    """When output_directory is not set, no disk write happens (existing behavior preserved)."""
    tool = FileGenerationTools()
    result = tool.generate_json_file({"x": 1}, filename="report.json")
    assert result.files[0].filepath is None
    assert result.files[0].content is not None

"""Tests for FileGenerationTools security and edge-case handling."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.exceptions import PathSecurityError
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
    """Empty filename must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "")


def test_dot_filename_raises():
    """Filename '.' must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", ".")


def test_dotdot_filename_raises():
    """Filename '..' must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "..")


def test_only_traversal_raises():
    """Filename '../' (path-only) must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "../")


def test_symlink_pointing_outside_rejected():
    """Symlink within output_directory pointing outside must be rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        outside_dir = Path(tmp_dir) / "outside"
        outside_dir.mkdir()
        inside_dir = Path(tmp_dir) / "inside"
        inside_dir.mkdir()
        try:
            (inside_dir / "escape").symlink_to(outside_dir)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")

        tool = FileGenerationTools(output_directory=str(inside_dir))
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            tool._save_file_to_disk("payload", "escape")


def test_security_violation_logs_error():
    """Security violations emit an error log via agno.utils.path_safety.log_error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with patch("agno.utils.path_safety.log_error") as mock_log_error:
            with pytest.raises(PathSecurityError):
                tool._save_file_to_disk("payload", "..")
        mock_log_error.assert_called_once()
        assert "Security violation" in str(mock_log_error.call_args)


def test_no_output_directory_returns_none_filepath():
    """When output_directory is not set, no disk write happens (existing behavior preserved)."""
    tool = FileGenerationTools()
    result = tool.generate_json_file({"x": 1}, filename="report.json")
    assert result.files is not None
    assert result.files[0].filepath is None
    assert result.files[0].content is not None


def test_control_char_filename_rejected():
    """Filenames containing control characters must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="control chars"):
            tool._save_file_to_disk("payload", "report\nhacked.json")


def test_whitespace_only_filename_rejected():
    """Whitespace-only filenames must raise PathSecurityError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "   ")


def test_trailing_dot_space_trimmed():
    """Trailing dots and spaces must be stripped (Windows MagicDot defense)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "report.json. ")
        assert (Path(tmp_dir) / "report.json").exists()


def test_generate_json_file_traversal_via_public_api():
    """Public-API integration: traversal via generate_json_file lands safely inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool.generate_json_file({"x": 1}, filename="../../../escape")
        assert (Path(tmp_dir) / "escape.json").exists()
        assert not (Path(tmp_dir).parent / "escape.json").exists()


def test_generate_csv_file_control_char_returns_error():
    """Public-API integration: control char in filename produces an error ToolResult (caught by except Exception)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        result = tool.generate_csv_file([{"a": 1}], filename="\n")
        assert "Error" in result.content


def test_pure_dot_filename_rejected():
    """Filename '...' must raise PathSecurityError after rstrip('. ')."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        with pytest.raises(PathSecurityError, match="Invalid filename"):
            tool._save_file_to_disk("payload", "...")


def test_url_encoded_traversal_sanitized_inside_output_directory():
    """URL-encoded traversal ('%2e%2e/...') is sanitized inside output_directory.

    Note: ``%2e%2e`` is NOT decoded by pathlib — it's a literal segment.
    ``Path(filename).name`` therefore takes ``escape``, and the file lands
    inside ``output_directory`` instead of escaping it. The original test
    name (``..._rejected``) was misleading because the input is sanitized,
    not rejected (no PathSecurityError raised).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        tool._save_file_to_disk("payload", "%2e%2e/escape")
        assert (Path(tmp_dir) / "escape").exists()
        assert not (Path(tmp_dir).parent / "escape").exists()


def test_filename_sanitized_in_artifact_traversal():
    """File.filename reflects the sanitized basename, not the LLM's original input (H2)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        result = tool.generate_json_file({"x": 1}, filename="../../../escape")
        assert result.files is not None
        artifact = result.files[0]
        # Single source of truth: filename matches the basename of filepath.
        assert artifact.filename == "escape.json"
        assert artifact.filepath is not None
        assert Path(artifact.filepath).name == artifact.filename


def test_filename_sanitized_no_output_directory():
    """File.filename is sanitized even when no disk write happens (H2)."""
    tool = FileGenerationTools()
    result = tool.generate_json_file({"x": 1}, filename="subdir/report.json")
    assert result.files is not None
    artifact = result.files[0]
    assert artifact.filename == "report.json"
    assert artifact.filepath is None


def test_filename_sanitized_subdir_collapsed():
    """File.filename matches the on-disk basename when subdir is stripped."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir)
        result = tool.generate_json_file({"x": 1}, filename="subdir/report.json")
        assert result.files is not None
        artifact = result.files[0]
        assert artifact.filename == "report.json"
        assert artifact.filepath is not None
        assert Path(artifact.filepath).name == "report.json"

"""Tests for SlackTools._save_file_to_disk path safety."""

import sys
import tempfile
from pathlib import Path

import pytest

from agno.tools.slack import SlackTools


def _make_slack_tools(output_dir: str) -> SlackTools:
    """Build SlackTools with a fake token for unit-testing _save_file_to_disk."""
    return SlackTools(token="fake-token-for-tests", output_directory=output_dir)


def test_traversal_filename_lands_inside_output_dir():
    """Traversal '../../escape' is sanitized via safe_join; file lands inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        result = tool._save_file_to_disk(b"payload", "../../escape.bin")
        assert result == str((Path(tmp_dir) / "escape.bin").resolve())
        assert (Path(tmp_dir) / "escape.bin").exists()
        assert not (Path(tmp_dir).parent / "escape.bin").exists()


def test_absolute_path_lands_inside_output_dir():
    """Absolute paths are stripped to bare filename via safe_join; file lands inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        result = tool._save_file_to_disk(b"payload", "/tmp/test_slack_abs_xyz.bin")
        assert result is not None
        assert (Path(tmp_dir) / "test_slack_abs_xyz.bin").exists()
        assert not Path("/tmp/test_slack_abs_xyz.bin").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_symlink_escape_returns_none():
    """Symlink within output_dir pointing outside is rejected; returns None."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        outside = Path(tmp_dir) / "outside"
        outside.mkdir()
        inside = Path(tmp_dir) / "inside"
        inside.mkdir()
        try:
            (inside / "escape").symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        tool = _make_slack_tools(str(inside))
        result = tool._save_file_to_disk(b"payload", "escape")
        assert result is None


def test_control_char_filename_returns_none():
    """Control character in filename is rejected by safe_join; SlackTools returns None."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        result = tool._save_file_to_disk(b"payload", "report\x00hacked.bin")
        assert result is None


def test_normal_filename_saves_correctly():
    """Happy path: 'report.bin' is written into output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        result = tool._save_file_to_disk(b"payload-bytes", "report.bin")
        assert result == str((Path(tmp_dir) / "report.bin").resolve())
        assert (Path(tmp_dir) / "report.bin").read_bytes() == b"payload-bytes"

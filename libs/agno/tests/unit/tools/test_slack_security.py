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
def test_symlink_escape_raises_path_security_error():
    """Symlink within output_dir pointing outside raises PathSecurityError (H3)."""
    from agno.exceptions import PathSecurityError

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
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            tool._save_file_to_disk(b"payload", "escape")


def test_control_char_filename_raises_path_security_error():
    """Control character in filename is rejected by safe_join; SlackTools raises (H3)."""
    from agno.exceptions import PathSecurityError

    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        with pytest.raises(PathSecurityError, match="control chars"):
            tool._save_file_to_disk(b"payload", "report\x00hacked.bin")


def test_normal_filename_saves_correctly():
    """Happy path: 'report.bin' is written into output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)
        result = tool._save_file_to_disk(b"payload-bytes", "report.bin")
        assert result == str((Path(tmp_dir) / "report.bin").resolve())
        assert (Path(tmp_dir) / "report.bin").read_bytes() == b"payload-bytes"


def test_save_file_oserror_returns_none(monkeypatch):
    """OSError is still swallowed (disk-full is advisory, not security)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = _make_slack_tools(tmp_dir)

        def _raise_oserror(self, _data):
            raise OSError("simulated disk full")

        monkeypatch.setattr(Path, "write_bytes", _raise_oserror)
        result = tool._save_file_to_disk(b"payload", "ok.bin")
        assert result is None

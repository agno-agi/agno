"""Tests for agno.utils.path_safety.safe_join and safe_join_subpath."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.exceptions import PathSecurityError
from agno.utils.path_safety import safe_join, safe_join_subpath


# ---------- TestSafeJoin (filename-only) ----------


def test_simple_filename_returns_resolved_path():
    """Plain filename joined with directory returns resolved absolute path."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "report.json")
        assert result == (Path(tmp) / "report.json").resolve()


def test_traversal_stripped_via_name():
    """Path components in filename are stripped; result lands in directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "../../../escape.json")
        assert result == (Path(tmp) / "escape.json").resolve()
        assert not (Path(tmp).parent / "escape.json").exists()


def test_absolute_path_stripped_via_name():
    """Absolute paths are stripped to bare filename."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "/tmp/test_abs_xyz.json")
        assert result.name == "test_abs_xyz.json"
        assert result.parent == Path(tmp).resolve()


@pytest.mark.parametrize(
    "evil",
    ["report\n.json", "report\r.json", "report\x00.json", "report\x07.json", "report\x1f.json", "report\x7f.json"],
)
def test_control_char_rejected(evil):
    """Filenames with control characters (Cc category, including DEL) are rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="control chars"):
            safe_join(tmp, evil)


def test_trailing_dot_space_stripped():
    """Trailing dots and spaces are stripped (Windows MagicDot defense)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "report.json. ")
        assert result.name == "report.json"


@pytest.mark.parametrize("invalid", ["", "   ", ".", "..", "..."])
def test_empty_or_dot_only_rejected(invalid):
    """Empty, whitespace-only, and dot-only filenames are rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Invalid filename|Empty"):
            safe_join(tmp, invalid)


def test_unicode_normalization_traversal_rejected():
    """NFKC-normalized fullwidth slash sequences must not escape directory."""
    with tempfile.TemporaryDirectory() as tmp:
        # FULLWIDTH SOLIDUS (U+FF0F) NFKC-normalizes to ASCII slash
        result = safe_join(tmp, "．．／escape")
        assert result.parent == Path(tmp).resolve()
        assert not (Path(tmp).parent / "escape").exists()


def test_url_encoded_traversal_landing_inside():
    """URL-encoded sequences are NOT decoded; literal characters land inside dir."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "%2e%2e/escape")
        assert result.parent == Path(tmp).resolve()


# ---------- TestSafeJoinSubpath (multi-segment) ----------


def test_simple_subpath_resolves_inside():
    """Plain subpath resolves inside the base directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join_subpath(tmp, "report.json")
        assert result == (Path(tmp) / "report.json").resolve()


def test_multi_segment_subpath_preserved():
    """Multi-segment subpaths are preserved (subdir/file.txt stays intact)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join_subpath(tmp, "subdir/file.txt")
        assert result == (Path(tmp) / "subdir" / "file.txt").resolve()


def test_traversal_subpath_rejected():
    """Subpath that escapes the base directory is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            safe_join_subpath(tmp, "../../escape")


def test_absolute_subpath_rejected():
    """Absolute subpath is rejected (escapes base directory)."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            safe_join_subpath(tmp, "/etc/passwd")


def test_control_char_subpath_rejected():
    """Subpath with control characters is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="control chars"):
            safe_join_subpath(tmp, "subdir/report\x00.json")


def test_empty_subpath_rejected():
    """Empty or whitespace-only subpath is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Empty subpath"):
            safe_join_subpath(tmp, "")


# ---------- TestSymlinkContainment (POSIX-only) ----------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_symlink_pointing_outside_rejected():
    """Symlink within base_dir pointing outside must be rejected by both helpers."""
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "outside"
        outside.mkdir()
        inside = Path(tmp) / "inside"
        inside.mkdir()
        try:
            (inside / "escape").symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            safe_join(str(inside), "escape")
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            safe_join_subpath(str(inside), "escape")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_symlinked_base_containment_enforced():
    """When base_dir itself is a symlink, both base and target are resolved (NIN-A1)."""
    with tempfile.TemporaryDirectory() as tmp:
        real_base = Path(tmp) / "real"
        real_base.mkdir()
        symlinked_base = Path(tmp) / "linked"
        try:
            symlinked_base.symlink_to(real_base)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        # Through the symlinked base, a normal subpath should still resolve inside.
        result = safe_join_subpath(str(symlinked_base), "child.txt")
        assert result == (real_base / "child.txt").resolve()


# ---------- TestLogging ----------


def test_security_violation_logs_error():
    """Security violations emit an error log via agno.utils.path_safety.log_error."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("agno.utils.path_safety.log_error") as mock_log_error:
            with pytest.raises(PathSecurityError):
                safe_join(tmp, "..")
        mock_log_error.assert_called_once()
        assert "Security violation" in str(mock_log_error.call_args)

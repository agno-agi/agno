"""Tests for agno.utils.path_safety."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.exceptions import PathSecurityError
from agno.utils.path_safety import safe_join, safe_join_subpath


def test_simple_filename_returns_resolved_path():
    """Test that a plain filename joins with the directory and resolves."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "report.json")
        assert result == (Path(tmp) / "report.json").resolve()


def test_traversal_stripped_via_name():
    """Test that path components in the filename are stripped to the basename."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "../../../escape.json")
        assert result == (Path(tmp) / "escape.json").resolve()
        assert not (Path(tmp).parent / "escape.json").exists()


def test_absolute_path_stripped_via_name():
    """Test that an absolute path is reduced to its basename."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "/tmp/test_abs_xyz.json")
        assert result.name == "test_abs_xyz.json"
        assert result.parent == Path(tmp).resolve()


@pytest.mark.parametrize(
    "evil",
    ["report\n.json", "report\r.json", "report\x00.json", "report\x07.json", "report\x1f.json", "report\x7f.json"],
)
def test_control_char_rejected(evil):
    """Test that filenames with control characters are rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="control chars"):
            safe_join(tmp, evil)


def test_trailing_dot_space_stripped():
    """Test that trailing dots and spaces are stripped from the filename."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "report.json. ")
        assert result.name == "report.json"


@pytest.mark.parametrize("invalid", ["", "   ", ".", "..", "..."])
def test_empty_or_dot_only_rejected(invalid):
    """Test that empty, whitespace-only, and dot-only filenames are rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Invalid filename|Empty"):
            safe_join(tmp, invalid)


def test_unicode_normalization_traversal_rejected():
    """Test that fullwidth-slash traversal does not escape the directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "．．／escape")
        assert result.parent == Path(tmp).resolve()
        assert not (Path(tmp).parent / "escape").exists()


def test_url_encoded_traversal_landing_inside():
    """Test that URL-encoded sequences are treated as literal characters."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "%2e%2e/escape")
        assert result.parent == Path(tmp).resolve()


def test_drive_letter_rejected_pre_strip():
    """Test that a Windows drive letter is rejected on the raw input."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="drive letter or UNC"):
            safe_join(tmp, "C:\\evil.txt")


def test_unc_path_rejected_pre_strip():
    """Test that a UNC prefix is rejected on the raw input."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="drive letter or UNC"):
            safe_join(tmp, "\\\\server\\share\\evil")


def test_control_char_in_path_component_rejected():
    """Test that a control character in a stripped path component is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="control chars"):
            safe_join(tmp, "\x00/safe.txt")


def test_simple_subpath_resolves_inside():
    """Test that a plain subpath resolves inside the base directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join_subpath(tmp, "report.json")
        assert result == (Path(tmp) / "report.json").resolve()


def test_multi_segment_subpath_preserved():
    """Test that multi-segment subpaths are preserved intact."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join_subpath(tmp, "subdir/file.txt")
        assert result == (Path(tmp) / "subdir" / "file.txt").resolve()


def test_traversal_subpath_rejected():
    """Test that a subpath escaping the base directory is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape|Empty segment"):
            safe_join_subpath(tmp, "../../escape")


def test_absolute_subpath_rejected():
    """Test that an absolute subpath is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="resolves outside|symlink escape"):
            safe_join_subpath(tmp, "/etc/passwd")


def test_control_char_subpath_rejected():
    """Test that a subpath with control characters is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="control chars"):
            safe_join_subpath(tmp, "subdir/report\x00.json")


def test_empty_subpath_rejected():
    """Test that an empty or whitespace-only subpath is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Empty subpath"):
            safe_join_subpath(tmp, "")


def test_subpath_reserved_segment_rejected():
    """Test that a Windows-reserved name in any segment is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Windows reserved"):
            safe_join_subpath(tmp, "docs/CON.txt")


def test_subpath_reserved_segment_with_backslash_rejected():
    """Test that backslash-separated segments are validated."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Windows reserved"):
            safe_join_subpath(tmp, "docs\\CON")


def test_subpath_drive_in_segment_rejected():
    """Test that a drive-prefixed subpath is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="must be relative|drive letter"):
            safe_join_subpath(tmp, "C:/evil.txt")


def test_subpath_unc_rejected():
    """Test that a UNC subpath is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="must be relative|drive letter"):
            safe_join_subpath(tmp, "\\\\server\\share\\evil")


def test_subpath_magicdot_segment_rejected():
    """Test that a trailing-dot segment stripping to a reserved name is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Windows reserved|Empty segment"):
            safe_join_subpath(tmp, "docs/CON.")


def test_subpath_magicdot_segment_stripped_to_canonical_name():
    """Test that trailing dots and spaces are stripped from non-reserved segments."""
    with tempfile.TemporaryDirectory() as tmp:
        assert safe_join_subpath(tmp, "a/name.").name == "name"
        assert safe_join_subpath(tmp, "name./b.txt").parent.name == "name"
        assert safe_join_subpath(tmp, "a/name .  /b.txt").parent.name == "name"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_symlink_pointing_outside_rejected():
    """Test that a symlink in the base directory pointing outside is rejected."""
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
    """Test that a symlinked base directory still resolves a normal subpath inside."""
    with tempfile.TemporaryDirectory() as tmp:
        real_base = Path(tmp) / "real"
        real_base.mkdir()
        symlinked_base = Path(tmp) / "linked"
        try:
            symlinked_base.symlink_to(real_base)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        result = safe_join_subpath(str(symlinked_base), "child.txt")
        assert result == (real_base / "child.txt").resolve()


def test_security_violation_logs_error():
    """Test that a security violation emits an error log."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("agno.utils.path_safety.log_error") as mock_log_error:
            with pytest.raises(PathSecurityError):
                safe_join(tmp, "..")
        mock_log_error.assert_called_once()
        assert "Security violation" in str(mock_log_error.call_args)


def test_safe_join_logs_warning_on_strip():
    """Test that safe_join warns when discarding path components."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("agno.utils.path_safety.log_warning") as mock_log_warning:
            safe_join(tmp, "subdir/report.json")
        mock_log_warning.assert_called_once()
        assert "discarded path components" in str(mock_log_warning.call_args)


def test_safe_join_no_warning_for_clean_basename():
    """Test that safe_join does not warn for a clean basename."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("agno.utils.path_safety.log_warning") as mock_log_warning:
            safe_join(tmp, "report.json")
        mock_log_warning.assert_not_called()


def test_safe_join_backslash_basename_extracted_on_posix():
    """Test that safe_join strips backslash-separated components on POSIX too."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join(tmp, "..\\..\\evil.bin")
        assert result.name == "evil.bin"
        assert result.parent == Path(tmp).resolve()


def test_safe_join_subpath_backslash_creates_nested_segments_on_posix():
    """Test that safe_join_subpath treats backslashes as separators on POSIX too."""
    with tempfile.TemporaryDirectory() as tmp:
        result = safe_join_subpath(tmp, "a\\b\\c.txt")
        assert result == (Path(tmp) / "a" / "b" / "c.txt").resolve()


def test_safe_join_lone_surrogate_raises_path_security_error():
    """Test that a lone surrogate half raises PathSecurityError, not UnicodeEncodeError."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Cannot resolve"):
            safe_join(tmp, "ev\ud800il.txt")


def test_safe_join_subpath_lone_surrogate_raises_path_security_error():
    """Test that safe_join_subpath also wraps surrogate-related errors."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError, match="Cannot resolve"):
            safe_join_subpath(tmp, "sub/ev\ud800il.txt")

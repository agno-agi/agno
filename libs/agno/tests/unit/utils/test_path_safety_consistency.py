"""Cross-tool consistency tests for path-safety helpers.

Verifies that the 5 callers (FileGenerationTools, SlackTools, Toolkit._check_path,
skills.utils.is_safe_path, FileTools.check_escape) handle the same evil inputs
with consistent semantics — accounting for the deliberate split between
safe_join_filename (filename-only) and safe_join_relative_path (multi-segment).
"""

import sys
import tempfile
from pathlib import Path

import pytest

from agno.exceptions import PathSecurityError
from agno.skills.utils import is_safe_path
from agno.tools import Toolkit
from agno.tools.file import FileTools
from agno.tools.file_generation import FileGenerationTools
from agno.tools.slack import SlackTools

# Inputs every caller rejects: control chars, empty, dot-dot.
ALL_REJECT = [
    "report\x00hacked.json",
    "report\nhacked",
    "report\rhacked",
    "",
    "..",
]

# Inputs that safe_join_filename rejects (filename-only); safe_join_relative_path sanitizes or accepts.
FILENAME_ONLY_REJECT = [
    "CON",
    ".",
    "...",
    "C:\\evil.txt",
    "\\\\server\\share\\evil",
]

# Inputs that safe_join_relative_path rejects (traversal); safe_join_filename sanitizes via Path.name.
SUBPATH_ONLY_REJECT = [
    "../../escape",
    "../../../etc/passwd",
    "/etc/passwd",
    "subdir/../../escape",
]


def _filegen(out: str) -> FileGenerationTools:
    return FileGenerationTools(output_directory=out)


def _slack(out: str) -> SlackTools:
    return SlackTools(token="fake-token-for-tests", output_directory=out)


def _toolkit() -> Toolkit:
    return Toolkit(name="cross-tool-test")


def _filetools(out: str) -> FileTools:
    return FileTools(base_dir=Path(out))


@pytest.mark.parametrize("evil", ALL_REJECT)
def test_all_callers_reject_universally(evil):
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", evil)
        assert fg_path is None
        assert fg_error is not None
        sl_path, sl_error = _slack(tmp)._save_file_to_disk(b"payload", evil)
        assert sl_path is None
        assert sl_error is not None
        ok, path = _toolkit()._check_path(evil, Path(tmp))
        assert ok is False
        assert path == Path(tmp)
        assert is_safe_path(Path(tmp), evil) is False
        ok, path = _filetools(tmp).check_escape(evil)
        assert ok is False


@pytest.mark.parametrize("evil", FILENAME_ONLY_REJECT)
def test_safe_join_filename_callers_reject_filename_evil(evil):
    """FileGen and Slack both return error tuple — refuse to write evil."""
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", evil)
        assert fg_path is None
        assert fg_error is not None
        sl_path, sl_error = _slack(tmp)._save_file_to_disk(b"payload", evil)
        assert sl_path is None
        assert sl_error is not None


@pytest.mark.parametrize("evil", SUBPATH_ONLY_REJECT)
def test_subpath_callers_reject_traversal(evil):
    """Toolkit + is_safe_path + FileTools reject traversal that escapes base_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        ok, path = _toolkit()._check_path(evil, Path(tmp))
        assert ok is False
        assert path == Path(tmp)
        assert is_safe_path(Path(tmp), evil) is False
        ok, path = _filetools(tmp).check_escape(evil)
        assert ok is False


# Subpath reserved segments / drive prefixes — rejected by per-segment validation
# (Commit 1: Windows hardening). Applies to all subpath-callers.
SUBPATH_RESERVED_REJECT = [
    "docs/CON.txt",
    "docs\\CON",
    "C:/evil.txt",
    "\\\\server\\share\\evil",
]


@pytest.mark.parametrize("evil", SUBPATH_RESERVED_REJECT)
def test_subpath_callers_reject_reserved_segment(evil):
    """Toolkit + is_safe_path + FileTools reject reserved segments / drive prefixes."""
    with tempfile.TemporaryDirectory() as tmp:
        ok, path = _toolkit()._check_path(evil, Path(tmp))
        assert ok is False
        assert path == Path(tmp)
        assert is_safe_path(Path(tmp), evil) is False
        ok, path = _filetools(tmp).check_escape(evil)
        assert ok is False


@pytest.mark.parametrize("evil", SUBPATH_ONLY_REJECT)
def test_safe_join_filename_callers_sanitize_traversal(evil):
    """FileGen + Slack sanitize traversal via Path(filename).name; file lands inside output_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", evil)
        assert fg_path is not None
        assert fg_error is None
        assert Path(fg_path).resolve().is_relative_to(Path(tmp).resolve())
        sl_path, sl_error = _slack(tmp)._save_file_to_disk(b"payload", evil)
        assert sl_path is not None
        assert sl_error is None
        assert Path(sl_path).resolve().is_relative_to(Path(tmp).resolve())


def test_adversarial_read_etc_passwd_via_filegen():
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("evil", "/etc/passwd")
        # safe_join_filename strips path components → file lands inside tmp as "passwd", NOT in /etc.
        assert fg_path is not None
        assert fg_error is None
        assert Path(fg_path).resolve().is_relative_to(Path(tmp).resolve())
        assert Path(fg_path).name == "passwd"


def test_adversarial_write_outside_via_slack():
    with tempfile.TemporaryDirectory() as tmp:
        sl_path, sl_error = _slack(tmp)._save_file_to_disk(b"evil", "/tmp/escape_via_slack_xyz.bin")
        assert sl_path is not None
        assert sl_error is None
        assert Path(sl_path).resolve().is_relative_to(Path(tmp).resolve())
        assert not Path("/tmp/escape_via_slack_xyz.bin").exists()


def test_adversarial_traverse_via_toolkit():
    with tempfile.TemporaryDirectory() as tmp:
        ok, path = _toolkit()._check_path("../../escape", Path(tmp))
        assert ok is False
        assert path == Path(tmp)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_adversarial_symlink_chain_attack():
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "outside"
        outside.mkdir()
        inside = Path(tmp) / "inside"
        inside.mkdir()
        try:
            (inside / "link").symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        fg_path, fg_error = _filegen(str(inside))._save_file_to_disk("payload", "link")
        assert fg_path is None
        assert fg_error is not None
        assert "resolves outside" in fg_error


def test_adversarial_unicode_normalization_attack():
    """U+FF0F FULLWIDTH SOLIDUS NFKC-normalizes; must not escape directory."""
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", "．．／escape")
        assert fg_path is not None
        assert fg_error is None
        assert Path(fg_path).resolve().is_relative_to(Path(tmp).resolve())


def test_adversarial_url_encoded_attack():
    """%2e%2e%2f is NOT decoded; treated as literal characters in filename."""
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", "%2e%2e%2fescape")
        assert fg_path is not None
        assert fg_error is None
        assert Path(fg_path).resolve().is_relative_to(Path(tmp).resolve())


def test_adversarial_null_byte_truncation_attack():
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", "report\x00.json")
        assert fg_path is None
        assert fg_error is not None


def test_adversarial_windows_drive_letter_attack():
    with tempfile.TemporaryDirectory() as tmp:
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", "C:\\evil.txt")
        assert fg_path is None
        assert fg_error is not None


def test_adversarial_long_filename_rejected_or_oserror():
    """A 4096-char filename must either return error or succeed inside output_dir — never silently land outside."""
    with tempfile.TemporaryDirectory() as tmp:
        long_name = "a" * 4096 + ".json"
        fg_path, fg_error = _filegen(tmp)._save_file_to_disk("payload", long_name)
        if fg_error is not None:
            return
        assert fg_path is not None, "implementation returned (None, None) — would silently drop the file"
        assert Path(fg_path).resolve().is_relative_to(Path(tmp).resolve())

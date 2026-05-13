"""Cross-tool consistency tests for path-safety helpers.

Verifies that the 5 callers (FileGenerationTools, SlackTools, Toolkit._check_path,
skills.utils.is_safe_path, FileTools.check_escape) handle the same evil inputs
with consistent semantics — accounting for the deliberate split between
safe_join (filename-only) and safe_join_subpath (multi-segment).
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

# Inputs that safe_join rejects (filename-only); safe_join_subpath sanitizes or accepts.
FILENAME_ONLY_REJECT = [
    "CON",
    ".",
    "...",
    "C:\\evil.txt",
    "\\\\server\\share\\evil",
]

# Inputs that safe_join_subpath rejects (traversal); safe_join sanitizes via Path.name.
SUBPATH_ONLY_REJECT = [
    "../../escape",
    "../../../etc/passwd",
    "/etc/passwd",
    "subdir/../../escape",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filegen(out: str) -> FileGenerationTools:
    return FileGenerationTools(output_directory=out)


def _slack(out: str) -> SlackTools:
    return SlackTools(token="fake-token-for-tests", output_directory=out)


def _toolkit() -> Toolkit:
    return Toolkit(name="cross-tool-test")


def _filetools(out: str) -> FileTools:
    return FileTools(base_dir=Path(out))


# ---------------------------------------------------------------------------
# Universal rejection — all 5 callers refuse the same inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evil", ALL_REJECT)
def test_all_callers_reject_universally(evil):
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError):
            _filegen(tmp)._save_file_to_disk("payload", evil)
        assert _slack(tmp)._save_file_to_disk(b"payload", evil) is None
        ok, path = _toolkit()._check_path(evil, Path(tmp))
        assert ok is False
        assert path == Path(tmp)
        assert is_safe_path(Path(tmp), evil) is False
        ok, path = _filetools(tmp).check_escape(evil)
        assert ok is False


# ---------------------------------------------------------------------------
# Filename-only rejection — safe_join callers refuse; subpath callers sanitize/accept
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evil", FILENAME_ONLY_REJECT)
def test_safe_join_callers_reject_filename_evil(evil):
    """FileGen raises, Slack drops the file silently — both refuse to write evil."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError):
            _filegen(tmp)._save_file_to_disk("payload", evil)
        assert _slack(tmp)._save_file_to_disk(b"payload", evil) is None


# ---------------------------------------------------------------------------
# Subpath rejection — subpath callers reject traversal; safe_join sanitizes
# ---------------------------------------------------------------------------


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
def test_safe_join_callers_sanitize_traversal(evil):
    """FileGen + Slack sanitize traversal via Path(filename).name; file lands inside output_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", evil)
        assert filegen_path is not None
        assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())
        slack_result = _slack(tmp)._save_file_to_disk(b"payload", evil)
        assert slack_result is not None
        assert Path(slack_result).resolve().is_relative_to(Path(tmp).resolve())


# ---------------------------------------------------------------------------
# Adversarial attacks — direct attempts to defeat path safety
# ---------------------------------------------------------------------------


def test_adversarial_read_etc_passwd_via_filegen():
    with tempfile.TemporaryDirectory() as tmp:
        filegen_path, safe_name = _filegen(tmp)._save_file_to_disk("evil", "/etc/passwd")
        # safe_join strips path components → file lands inside tmp as "passwd", NOT in /etc.
        assert filegen_path is not None
        assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())
        assert safe_name == "passwd"


def test_adversarial_write_outside_via_slack():
    with tempfile.TemporaryDirectory() as tmp:
        result = _slack(tmp)._save_file_to_disk(b"evil", "/tmp/escape_via_slack_xyz.bin")
        assert result is not None
        assert Path(result).resolve().is_relative_to(Path(tmp).resolve())
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
        with pytest.raises(PathSecurityError):
            _filegen(str(inside))._save_file_to_disk("payload", "link")


def test_adversarial_unicode_normalization_attack():
    """U+FF0F FULLWIDTH SOLIDUS NFKC-normalizes; must not escape directory."""
    with tempfile.TemporaryDirectory() as tmp:
        filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", "．．／escape")
        assert filegen_path is not None
        assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())


def test_adversarial_url_encoded_attack():
    """%2e%2e%2f is NOT decoded; treated as literal characters in filename."""
    with tempfile.TemporaryDirectory() as tmp:
        filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", "%2e%2e%2fescape")
        assert filegen_path is not None
        assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())


def test_adversarial_null_byte_truncation_attack():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError):
            _filegen(tmp)._save_file_to_disk("payload", "report\x00.json")


def test_adversarial_windows_drive_letter_attack():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError):
            _filegen(tmp)._save_file_to_disk("payload", "C:\\evil.txt")


def test_adversarial_long_filename_rejected_or_oserror():
    """A 4096-char filename must either be rejected or surface OSError — never silently land outside."""
    with tempfile.TemporaryDirectory() as tmp:
        long_name = "a" * 4096 + ".json"
        try:
            filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", long_name)
        except (PathSecurityError, OSError):
            return
        assert filegen_path is not None, "implementation returned None without raising — would silently drop the file"
        assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())

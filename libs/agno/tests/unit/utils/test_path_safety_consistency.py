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

# ---------------------------------------------------------------------------
# Input categories
# ---------------------------------------------------------------------------

# Universally-rejected: every caller refuses these (control chars, empty/dotdot)
ALL_REJECT = [
    "report\x00hacked.json",  # CWE-117 null byte
    "report\nhacked",  # CWE-117 newline
    "report\rhacked",  # CWE-117 CR
    "",  # empty
    "..",  # dot-dot escapes via is_relative_to and rstrip
]

# Filename-only rejection: safe_join (FileGen, Slack) refuses; safe_join_subpath
# callers (Toolkit, is_safe_path, FileTools) sanitize or accept.
FILENAME_ONLY_REJECT = [
    "CON",  # CWE-635 Windows reserved
    ".",  # dot — safe_join rejects (empty after strip); subpath accepts (resolves to base)
    "...",  # dot-only — safe_join rejects after rstrip
    "C:\\evil.txt",  # Windows drive prefix
    "\\\\server\\share\\evil",  # UNC prefix
]

# Subpath rejection: safe_join_subpath (Toolkit, is_safe_path, FileTools)
# refuses traversal; safe_join (FileGen, Slack) silently sanitizes via
# Path(filename).name.
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
        with pytest.raises(PathSecurityError):
            _slack(tmp)._save_file_to_disk(b"payload", evil)
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
    """FileGen + Slack reject filename-level evil; subpath callers may accept."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PathSecurityError):
            _filegen(tmp)._save_file_to_disk("payload", evil)
        with pytest.raises(PathSecurityError):
            _slack(tmp)._save_file_to_disk(b"payload", evil)


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
        if filegen_path is not None:
            assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())
        slack_result = _slack(tmp)._save_file_to_disk(b"payload", evil)
        if slack_result is not None:
            assert Path(slack_result).resolve().is_relative_to(Path(tmp).resolve())


# ---------------------------------------------------------------------------
# Adversarial attacks — direct attempts to defeat path safety
# ---------------------------------------------------------------------------


class TestAdversarialAttacks:
    """Direct attempts to defeat path safety. ALL must fail."""

    def test_read_etc_passwd_via_filegen(self):
        with tempfile.TemporaryDirectory() as tmp:
            filegen_path, safe_name = _filegen(tmp)._save_file_to_disk("evil", "/etc/passwd")
            # safe_join strips path components → file lands inside tmp as "passwd", NOT in /etc.
            assert filegen_path is not None
            assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())
            assert safe_name == "passwd"

    def test_write_outside_via_slack(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _slack(tmp)._save_file_to_disk(b"evil", "/tmp/escape_via_slack_xyz.bin")
            if result is not None:
                assert Path(result).resolve().is_relative_to(Path(tmp).resolve())
            assert not Path("/tmp/escape_via_slack_xyz.bin").exists()

    def test_traverse_via_toolkit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, path = _toolkit()._check_path("../../escape", Path(tmp))
            assert ok is False
            assert path == Path(tmp)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
    def test_symlink_chain_attack(self):
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

    def test_unicode_normalization_attack(self):
        """U+FF0F FULLWIDTH SOLIDUS NFKC-normalizes; must not escape directory."""
        with tempfile.TemporaryDirectory() as tmp:
            filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", "．．／escape")
            if filegen_path is not None:
                assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())

    def test_url_encoded_attack(self):
        """%2e%2e%2f is NOT decoded; treated as literal characters in filename."""
        with tempfile.TemporaryDirectory() as tmp:
            filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", "%2e%2e%2fescape")
            if filegen_path is not None:
                assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())

    def test_null_byte_truncation_attack(self):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(PathSecurityError):
                _filegen(tmp)._save_file_to_disk("payload", "report\x00.json")

    def test_windows_drive_letter_attack(self):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(PathSecurityError):
                _filegen(tmp)._save_file_to_disk("payload", "C:\\evil.txt")

    def test_long_filename_handled_gracefully(self):
        """4096-char filename: must reject or handle OSError without leaking."""
        with tempfile.TemporaryDirectory() as tmp:
            long_name = "a" * 4096 + ".json"
            try:
                filegen_path, _ = _filegen(tmp)._save_file_to_disk("payload", long_name)
                if filegen_path is not None:
                    assert Path(filegen_path).resolve().is_relative_to(Path(tmp).resolve())
            except (PathSecurityError, OSError):
                pass  # Either rejection path is acceptable

"""Tests for Toolkit._check_path post-migration to safe_join_subpath.

Verifies the (bool, Path) contract is preserved, multi-segment paths still
work (regression for test_python_tools.py:179 / test_agent_skills.py:449),
the symlinked-base bypass is fixed, and the restrict_to_base_dir=False
escape-hatch still functions.
"""

import sys
import tempfile
from pathlib import Path

import pytest

from agno.tools import Toolkit


def _toolkit() -> Toolkit:
    """Build a bare Toolkit instance to access the inherited _check_path."""
    return Toolkit(name="test-toolkit")


def test_check_path_simple_filename_returns_true():
    """Plain filename inside base_dir returns (True, resolved_path)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        ok, path = _toolkit()._check_path("report.json", base)
        assert ok is True
        assert path == (base / "report.json").resolve()


def test_check_path_multi_segment_subdir_returns_resolved_path():
    """Multi-segment subdir/file path is preserved (regression for test_agent_skills.py:449)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        ok, path = _toolkit()._check_path("subdir/file.txt", base)
        assert ok is True
        assert path == (base / "subdir" / "file.txt").resolve()


def test_check_path_subdir_traversal_returns_false_with_base_dir():
    """Subdir traversal escape returns (False, base_dir) — regression for test_python_tools.py:179."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        ok, path = _toolkit()._check_path("subdir/../../escape.py", base)
        assert ok is False
        assert path == base


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_check_path_symlinked_base_containment_enforced():
    """Symlinked base_dir does not bypass containment (resolves both paths)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        outside = Path(tmp_dir) / "outside"
        outside.mkdir()
        inside = Path(tmp_dir) / "inside"
        inside.mkdir()
        try:
            (inside / "escape").symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        ok, path = _toolkit()._check_path("escape", inside)
        assert ok is False
        assert path == inside


def test_check_path_restrict_false_returns_resolved_outside():
    """restrict_to_base_dir=False escape-hatch returns (True, resolved) without containment check."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        ok, path = _toolkit()._check_path("../../somewhere.txt", base, restrict_to_base_dir=False)
        assert ok is True
        # Path resolves outside base_dir; with restrict=False, that's allowed.
        assert path == base.joinpath("../../somewhere.txt").resolve()

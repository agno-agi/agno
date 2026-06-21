"""Tests for path traversal protection in LocalFileSystemTools."""

import os
import tempfile
from pathlib import Path

import pytest

from agno.tools.local_file_system import LocalFileSystemTools


@pytest.fixture
def tmp_dir(tmp_path):
    """Create a temp directory for testing."""
    return str(tmp_path)


@pytest.fixture
def tools(tmp_dir):
    """Create a LocalFileSystemTools instance."""
    return LocalFileSystemTools(target_directory=tmp_dir, enable_write_file=True)


class TestPathTraversalWriteFile:
    """Tests for path traversal protection in write_file."""

    def test_normal_write_succeeds(self, tools, tmp_dir):
        """Normal file write should succeed."""
        result = tools.write_file(content="hello", filename="test.txt")
        assert "Successfully wrote" in result
        assert Path(tmp_dir, "test.txt").exists()

    def test_dot_dot_slash_blocked(self, tools):
        """Path traversal with ../ should be blocked."""
        result = tools.write_file(content="malicious", filename="../evil.txt")
        assert "Path traversal detected" in result

    def test_dot_dot_slash_nested_blocked(self, tools):
        """Nested path traversal with ../../ should be blocked."""
        result = tools.write_file(content="malicious", filename="../../etc/passwd")
        assert "Path traversal detected" in result

    def test_dot_dot_slash_in_directory_blocked(self, tools):
        """Path traversal in directory parameter should be blocked."""
        result = tools.write_file(content="malicious", filename="test", directory="/tmp/../../../etc")
        assert "Path traversal detected" in result

    def test_absolute_path_outside_base_blocked(self, tools):
        """Absolute path outside base directory should be blocked."""
        result = tools.write_file(content="malicious", filename="/etc/passwd")
        assert "Path traversal detected" in result

    def test_dot_dot_no_separator_still_blocked(self, tools):
        """Path like '..' alone should be blocked."""
        result = tools.write_file(content="malicious", filename="..")
        assert "Path traversal detected" in result


class TestPathTraversalReadFile:
    """Tests for path traversal protection in read_file."""

    def test_normal_read_succeeds(self, tools, tmp_dir):
        """Normal file read should succeed."""
        test_file = Path(tmp_dir, "readme.txt")
        test_file.write_text("content")
        result = tools.read_file(filename="readme.txt")
        assert result == "content"

    def test_dot_dot_slash_blocked(self, tools):
        """Path traversal with ../ should be blocked."""
        result = tools.read_file(filename="../etc/passwd")
        assert "Path traversal detected" in result

    def test_dot_dot_slash_nested_blocked(self, tools):
        """Nested path traversal should be blocked."""
        result = tools.read_file(filename="../../etc/shadow")
        assert "Path traversal detected" in result

    def test_absolute_path_outside_base_blocked(self, tools):
        """Absolute path outside base should be blocked."""
        result = tools.read_file(filename="/etc/passwd")
        assert "Path traversal detected" in result

    def test_dot_dot_alone_blocked(self, tools):
        """Path '..' alone should be blocked."""
        result = tools.read_file(filename="..")
        assert "Path traversal detected" in result

    def test_symlink_traversal_blocked(self, tools, tmp_dir):
        """Symlink that escapes base directory should be blocked."""
        link = Path(tmp_dir, "escape_link")
        link.symlink_to("/etc")
        result = tools.read_file(filename="escape_link/passwd")
        assert "Path traversal detected" in result

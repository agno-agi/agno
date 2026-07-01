"""Unit tests for LocalFileSystemTools class."""

import tempfile
from pathlib import Path

import pytest

from agno.tools.local_file_system import LocalFileSystemTools


@pytest.fixture
def temp_dir():
    """Create a temporary directory for file system tests."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def tools(temp_dir):
    """Create a LocalFileSystemTools instance with default settings."""
    return LocalFileSystemTools(target_directory=temp_dir)


@pytest.fixture
def write_only_tools(temp_dir):
    """Create a write-only LocalFileSystemTools instance."""
    return LocalFileSystemTools(target_directory=temp_dir, enable_read_file=False)


@pytest.fixture
def read_only_tools(temp_dir):
    """Create a read-only LocalFileSystemTools instance."""
    return LocalFileSystemTools(target_directory=temp_dir, enable_write_file=False)


# --- Tool Registration ---


def test_default_registers_both_tools(tools):
    """Default initialization registers both write_file and read_file."""
    names = [f.name for f in tools.functions.values()]
    assert "write_file" in names
    assert "read_file" in names


def test_write_only_disables_read_file(write_only_tools):
    """enable_read_file=False excludes read_file from the tools list."""
    names = [f.name for f in write_only_tools.functions.values()]
    assert "write_file" in names
    assert "read_file" not in names


def test_read_only_disables_write_file(read_only_tools):
    """enable_write_file=False excludes write_file from the tools list."""
    names = [f.name for f in read_only_tools.functions.values()]
    assert "read_file" in names
    assert "write_file" not in names


def test_all_flag_registers_both(temp_dir):
    """all=True registers both tools regardless of individual flags."""
    t = LocalFileSystemTools(target_directory=temp_dir, enable_write_file=False, enable_read_file=False, all=True)
    names = [f.name for f in t.functions.values()]
    assert "write_file" in names
    assert "read_file" in names


def test_both_disabled_registers_nothing(temp_dir):
    """Disabling both tools with enable flags registers no tools."""
    t = LocalFileSystemTools(target_directory=temp_dir, enable_write_file=False, enable_read_file=False)
    names = [f.name for f in t.functions.values()]
    assert "write_file" not in names
    assert "read_file" not in names


def test_toolkit_name_is_local_file_system(tools):
    """Toolkit name is 'local_file_system'."""
    assert tools.name == "local_file_system"


# --- Write File ---


def test_write_file_creates_file(tools, temp_dir):
    """write_file creates a file with the given content."""
    result = tools.write_file("hello world", filename="test")
    assert "Successfully wrote file to:" in result

    filepath = Path(temp_dir) / "test.txt"
    assert filepath.exists()
    assert filepath.read_text() == "hello world"


def test_write_file_default_extension(tools, temp_dir):
    """write_file uses default_extension when no extension specified."""
    t = LocalFileSystemTools(target_directory=temp_dir, default_extension="md")
    t.write_file("# Hello", filename="readme")
    filepath = Path(temp_dir) / "readme.md"
    assert filepath.exists()
    assert filepath.read_text() == "# Hello"


def test_write_file_custom_extension(tools, temp_dir):
    """write_file respects the extension parameter."""
    tools.write_file("print('hi')", filename="script", extension="py")
    filepath = Path(temp_dir) / "script.py"
    assert filepath.exists()
    assert filepath.read_text() == "print('hi')"


def test_write_file_filename_with_dot_parses_extension(tools, temp_dir):
    """Filename containing a dot uses the suffix as extension."""
    tools.write_file("content", filename="data.json")
    filepath = Path(temp_dir) / "data.json"
    assert filepath.exists()


def test_write_file_custom_directory(tools, temp_dir):
    """write_file uses the directory parameter when provided."""
    subdir = Path(temp_dir) / "subdir"
    tools.write_file("nested", filename="nested_file", directory=str(subdir))
    filepath = subdir / "nested_file.txt"
    assert filepath.exists()
    assert filepath.read_text() == "nested"


def test_write_file_generates_uuid_filename(tools, temp_dir):
    """write_file generates a UUID-based filename when none is provided."""
    result = tools.write_file("auto name")
    assert "Successfully wrote file to:" in result

    path_str = result.split("Successfully wrote file to: ")[1]
    filepath = Path(path_str)
    assert filepath.exists()
    assert filepath.read_text() == "auto name"


# --- Read File ---


def test_read_file_returns_content(tools, temp_dir):
    """read_file returns the content of an existing file."""
    filepath = Path(temp_dir) / "greeting.txt"
    filepath.write_text("hello from test")

    result = tools.read_file("greeting.txt")
    assert result == "hello from test"


def test_read_file_missing_returns_error(tools, temp_dir):
    """read_file returns a 'File not found' message for missing files."""
    result = tools.read_file("nonexistent.txt")
    assert "File not found:" in result


def test_read_file_custom_directory(tools, temp_dir):
    """read_file reads from the specified directory."""
    subdir = Path(temp_dir) / "data"
    subdir.mkdir(parents=True)
    filepath = subdir / "info.txt"
    filepath.write_text("custom dir content")

    result = tools.read_file("info.txt", directory=str(subdir))
    assert result == "custom dir content"


# --- Write + Read Round-Trip ---


def test_write_read_round_trip(tools, temp_dir):
    """A write followed by a read returns the original content."""
    tools.write_file("round-trip test", filename="roundtrip")
    result = tools.read_file("roundtrip.txt")
    assert result == "round-trip test"


# --- Target Directory ---


def test_target_directory_created_if_missing():
    """The target_directory is created if it doesn't exist."""
    with tempfile.TemporaryDirectory() as base:
        nested = Path(base) / "nested" / "dir"
        LocalFileSystemTools(target_directory=str(nested))
        assert nested.exists()


def test_target_directory_defaults_to_cwd():
    """target_directory defaults to the current working directory."""
    t = LocalFileSystemTools()
    assert t.target_directory == str(Path.cwd())


# --- Error Handling ---


def test_write_file_error_is_caught(tools, temp_dir):
    """write_file catches exceptions and returns an error message."""
    result = tools.write_file("content", directory="/nonexistent/path/that/will/fail")
    assert "Error:" in result


def test_write_file_logs_debug(tools, temp_dir):
    """write_file calls log_debug during execution."""
    from unittest.mock import patch

    with patch("agno.tools.local_file_system.log_debug") as mock_debug:
        tools.write_file("hello", filename="debug_test")
        mock_debug.assert_called_once()

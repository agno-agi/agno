"""Unit tests for ShellTools class."""

import json
import platform
from pathlib import Path

import pytest

from agno.tools.shell import DEFAULT_BLACKLIST, ShellTools


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def shell_tools(temp_dir):
    """Create ShellTools instance with temp directory."""
    return ShellTools(base_dir=str(temp_dir), all=True)


@pytest.fixture
def shell_tools_with_blacklist(temp_dir):
    """Create ShellTools instance with blacklist enabled."""
    return ShellTools(base_dir=str(temp_dir), enable_blacklist=True, all=True)


def test_init_default():
    """Test initialization with default parameters."""
    tools = ShellTools()

    assert tools.base_dir == Path.cwd()
    assert tools.current_dir == Path.cwd()
    assert tools.enable_blacklist is False
    assert tools.timeout == 30
    assert tools.os_type == platform.system()


def test_init_with_custom_params(temp_dir):
    """Test initialization with custom parameters."""
    custom_blacklist = {"dangerous_command"}
    tools = ShellTools(
        base_dir=str(temp_dir),
        enable_blacklist=True,
        blacklist=custom_blacklist,
        timeout=60,
    )

    assert tools.base_dir == temp_dir
    assert tools.enable_blacklist is True
    assert tools.blacklist == custom_blacklist
    assert tools.timeout == 60


def test_init_with_all_tools():
    """Test initialization with all tools enabled."""
    tools = ShellTools(all=True)

    function_names = [func.name for func in tools.functions.values()]
    assert "run_shell_command" in function_names
    assert "change_directory" in function_names
    assert "get_current_directory" in function_names
    assert "list_files" in function_names
    assert "get_os_info" in function_names


def test_init_with_selective_tools():
    """Test initialization with selective tools."""
    tools = ShellTools(
        enable_run_shell_command=True,
        enable_change_directory=False,
        enable_get_current_directory=True,
        enable_list_files=False,
        enable_get_os_info=True,
    )

    function_names = [func.name for func in tools.functions.values()]
    assert "run_shell_command" in function_names
    assert "change_directory" not in function_names
    assert "get_current_directory" in function_names
    assert "list_files" not in function_names
    assert "get_os_info" in function_names


def test_run_shell_command_success(shell_tools):
    """Test successful shell command execution."""
    # Use a simple command that works on all platforms
    if platform.system() == "Windows":
        cmd = ["cmd", "/c", "echo hello"]
    else:
        cmd = ["echo", "hello"]

    result = shell_tools.run_shell_command(cmd)
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert result_data["return_code"] == 0
    assert "hello" in result_data["stdout"].lower()
    assert result_data["command"] == " ".join(cmd)
    assert result_data["os"] == platform.system()


def test_run_shell_command_with_tail(shell_tools):
    """Test shell command with tail parameter."""
    if platform.system() == "Windows":
        # Create multi-line output on Windows
        cmd = ["cmd", "/c", "echo line1 && echo line2 && echo line3"]
    else:
        cmd = ["sh", "-c", "echo line1; echo line2; echo line3"]

    result = shell_tools.run_shell_command(cmd, tail=2)
    result_data = json.loads(result)

    assert result_data["success"] is True
    lines = [line for line in result_data["stdout"].split("\n") if line.strip()]
    assert len(lines) <= 2


def test_run_shell_command_error(shell_tools):
    """Test shell command that returns error."""
    cmd = ["nonexistent_command_12345"]

    result = shell_tools.run_shell_command(cmd)
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert "error" in result_data


def test_run_shell_command_timeout(shell_tools):
    """Test shell command timeout."""
    if platform.system() == "Windows":
        cmd = ["ping", "127.0.0.1", "-n", "10"]  # 10 pings, will timeout
    else:
        cmd = ["sleep", "10"]

    result = shell_tools.run_shell_command(cmd, timeout=1)
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert "timeout" in result_data
    assert result_data["timeout"] is True


def test_blacklist_command_blocked(shell_tools_with_blacklist):
    """Test that blacklisted commands are blocked."""
    cmd = ["rm", "-rf", "/"]

    result = shell_tools_with_blacklist.run_shell_command(cmd)
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert result_data["blocked"] is True
    assert "blacklist" in result_data["error"].lower()


def test_blacklist_disabled(shell_tools):
    """Test that blacklist doesn't block when disabled."""
    # Note: We're not actually running dangerous commands, just checking the flag
    assert shell_tools.enable_blacklist is False
    assert not shell_tools._is_command_blacklisted(["rm", "-rf", "/"])


def test_custom_blacklist(temp_dir):
    """Test custom blacklist."""
    custom_blacklist = {"mycommand", "dangerous"}
    tools = ShellTools(base_dir=str(temp_dir), enable_blacklist=True, blacklist=custom_blacklist)

    assert tools._is_command_blacklisted(["mycommand", "arg1"])
    assert tools._is_command_blacklisted(["dangerous"])
    assert not tools._is_command_blacklisted(["safe_command"])


def test_change_directory(shell_tools, temp_dir):
    """Test changing directory."""
    # Create a subdirectory
    subdir = temp_dir / "subdir"
    subdir.mkdir()

    result = shell_tools.change_directory("subdir")
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert Path(result_data["current_directory"]) == subdir
    assert shell_tools.current_dir == subdir


def test_change_directory_absolute_path(shell_tools, temp_dir):
    """Test changing directory with absolute path."""
    subdir = temp_dir / "subdir"
    subdir.mkdir()

    result = shell_tools.change_directory(str(subdir))
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert Path(result_data["current_directory"]) == subdir


def test_change_directory_nonexistent(shell_tools):
    """Test changing to nonexistent directory."""
    result = shell_tools.change_directory("nonexistent_dir_12345")
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert "does not exist" in result_data["error"]


def test_change_directory_to_file(shell_tools, temp_dir):
    """Test changing directory to a file (should fail)."""
    # Create a file
    test_file = temp_dir / "test.txt"
    test_file.write_text("test")

    result = shell_tools.change_directory("test.txt")
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert "not a directory" in result_data["error"]


def test_get_current_directory(shell_tools, temp_dir):
    """Test getting current directory."""
    result = shell_tools.get_current_directory()
    result_data = json.loads(result)

    assert "current_directory" in result_data
    assert Path(result_data["current_directory"]) == temp_dir
    assert "absolute_path" in result_data


def test_list_files(shell_tools, temp_dir):
    """Test listing files in directory."""
    # Create some test files and directories
    (temp_dir / "file1.txt").write_text("test1")
    (temp_dir / "file2.txt").write_text("test2")
    (temp_dir / "subdir1").mkdir()
    (temp_dir / "subdir2").mkdir()

    result = shell_tools.list_files()
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert result_data["total_files"] == 2
    assert result_data["total_directories"] == 2
    assert len(result_data["files"]) == 2
    assert len(result_data["directories"]) == 2


def test_list_files_with_pattern(shell_tools, temp_dir):
    """Test listing files with pattern."""
    (temp_dir / "test.txt").write_text("test")
    (temp_dir / "test.log").write_text("log")
    (temp_dir / "file.txt").write_text("file")

    result = shell_tools.list_files(pattern="*.txt")
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert result_data["pattern"] == "*.txt"
    assert result_data["total_files"] == 2
    assert all("txt" in f["name"] for f in result_data["files"])


def test_list_files_specific_path(shell_tools, temp_dir):
    """Test listing files in specific path."""
    subdir = temp_dir / "subdir"
    subdir.mkdir()
    (subdir / "file.txt").write_text("test")

    result = shell_tools.list_files(path="subdir")
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert "subdir" in result_data["directory"]
    assert result_data["total_files"] == 1


def test_list_files_nonexistent_directory(shell_tools):
    """Test listing files in nonexistent directory."""
    result = shell_tools.list_files(path="nonexistent_dir")
    result_data = json.loads(result)

    assert result_data["success"] is False
    assert "does not exist" in result_data["error"]


def test_get_os_info(shell_tools):
    """Test getting OS information."""
    result = shell_tools.get_os_info()
    result_data = json.loads(result)

    assert "os" in result_data
    assert "platform" in result_data
    assert "architecture" in result_data
    assert "python_version" in result_data
    assert result_data["os"] == platform.system()


def test_get_os_info_platform_specific(shell_tools):
    """Test OS-specific information."""
    result = shell_tools.get_os_info()
    result_data = json.loads(result)

    os_type = platform.system()
    if os_type == "Windows":
        assert "windows_version" in result_data
    elif os_type == "Linux":
        assert "linux_distribution" in result_data
    elif os_type == "Darwin":
        assert "mac_version" in result_data


def test_default_blacklist():
    """Test that default blacklist contains dangerous commands."""
    assert "rm -rf /" in DEFAULT_BLACKLIST
    assert "format" in DEFAULT_BLACKLIST
    assert "mkfs" in DEFAULT_BLACKLIST


def test_command_runs_in_current_directory(shell_tools, temp_dir):
    """Test that commands run in the current directory context."""
    # Change to a subdirectory
    subdir = temp_dir / "subdir"
    subdir.mkdir()
    shell_tools.change_directory("subdir")

    # Create a file in current directory
    test_file = subdir / "test.txt"
    test_file.write_text("test")

    # Run command that references the file
    if platform.system() == "Windows":
        cmd = ["cmd", "/c", "dir", "test.txt"]
    else:
        cmd = ["ls", "test.txt"]

    result = shell_tools.run_shell_command(cmd)
    result_data = json.loads(result)

    assert result_data["success"] is True
    assert "test.txt" in result_data["stdout"]


def test_toolkit_name():
    """Test that toolkit has correct name."""
    tools = ShellTools()
    assert tools.name == "shell_tools"


def test_json_output_format(shell_tools):
    """Test that all outputs are valid JSON."""
    # Test all functions return valid JSON
    results = [
        shell_tools.run_shell_command(["echo", "test"]),
        shell_tools.get_current_directory(),
        shell_tools.list_files(),
        shell_tools.get_os_info(),
    ]

    for result in results:
        # Should not raise exception
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

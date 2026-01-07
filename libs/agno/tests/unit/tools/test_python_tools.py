import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.tools.python import PythonTools


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def python_tools(temp_dir):
    return PythonTools(
        base_dir=temp_dir,
        include_tools=[
            "save_to_file_and_run",
            "run_python_code",
            "pip_install_package",
            "uv_pip_install_package",
            "run_python_file_return_variable",
            "read_file",
            "list_files",
        ],
    )


def test_save_to_file_and_run_success(python_tools, temp_dir):
    # Test successful code execution
    code = "x = 42"
    result = python_tools.save_to_file_and_run("test.py", code, "x")
    assert result == "42"
    assert (temp_dir / "test.py").exists()
    assert (temp_dir / "test.py").read_text() == code


def test_save_to_file_and_run_error(python_tools):
    # Test code with syntax error
    code = "x = "  # Invalid syntax
    result = python_tools.save_to_file_and_run("test.py", code)
    assert "Error saving and running code" in result


def test_save_to_file_and_run_no_overwrite(python_tools, temp_dir):
    # Test file overwrite prevention
    file_path = temp_dir / "test.py"
    file_path.write_text("original")

    result = python_tools.save_to_file_and_run("test.py", "new code", overwrite=False)
    assert "already exists" in result
    assert file_path.read_text() == "original"


def test_run_python_file_return_variable(python_tools, temp_dir):
    # Test running existing file and returning variable
    file_path = temp_dir / "test.py"
    file_path.write_text("x = 42")

    result = python_tools.run_python_file_return_variable("test.py", "x")
    assert result == "42"


def test_run_python_file_return_variable_not_found(python_tools, temp_dir):
    # Test running file with non-existent variable
    file_path = temp_dir / "test.py"
    file_path.write_text("x = 42")

    result = python_tools.run_python_file_return_variable("test.py", "y")
    assert "Variable y not found" in result


def test_read_file(python_tools, temp_dir):
    # Test reading file contents
    file_path = temp_dir / "test.txt"
    content = "Hello, World!"
    file_path.write_text(content)

    result = python_tools.read_file("test.txt")
    assert result == content


def test_read_file_not_found(python_tools):
    # Test reading non-existent file
    result = python_tools.read_file("nonexistent.txt")
    assert "Error reading file" in result


def test_list_files(python_tools, temp_dir):
    # Test listing files in directory
    (temp_dir / "file1.txt").touch()
    (temp_dir / "file2.txt").touch()

    result = python_tools.list_files()
    assert "file1.txt" in result
    assert "file2.txt" in result


def test_run_python_code(python_tools):
    # Test running Python code directly
    code = "x = 42"
    result = python_tools.run_python_code(code, "x")
    assert result == "42"


def test_run_python_code_advanced(python_tools):
    # Test running Python code directly
    code = """
def fibonacci(n, print_steps: bool = False):
    a, b = 0, 1
    for _ in range(n):
        if print_steps:
            print(a)
        a, b = b, a + b
    return a

result = fibonacci(10, print_steps=True)
    """
    result = python_tools.run_python_code(code, "result")
    assert result == "55"


def test_run_python_code_error(python_tools):
    # Test running invalid Python code
    code = "x = "  # Invalid syntax
    result = python_tools.run_python_code(code)
    assert "Error running python code" in result


@patch("subprocess.check_call")
def test_pip_install_package(mock_check_call, python_tools):
    # Test pip package installation
    result = python_tools.pip_install_package("requests")
    assert "successfully installed package requests" in result
    mock_check_call.assert_called_once()


@patch("subprocess.check_call")
def test_pip_install_package_error(mock_check_call, python_tools):
    # Test pip package installation error
    mock_check_call.side_effect = Exception("Installation failed")
    result = python_tools.pip_install_package("requests")
    assert "Error installing package requests" in result


@patch("subprocess.check_call")
def test_uv_pip_install_package(mock_check_call, python_tools):
    # Test uv pip package installation
    result = python_tools.uv_pip_install_package("requests")
    assert "successfully installed package requests" in result
    mock_check_call.assert_called_once()


@patch("subprocess.check_call")
def test_uv_pip_install_package_error(mock_check_call, python_tools):
    # Test uv pip package installation error
    mock_check_call.side_effect = Exception("Installation failed")
    result = python_tools.uv_pip_install_package("requests")
    assert "Error installing package requests" in result


# Path traversal prevention tests
def test_check_path_blocks_parent_traversal(temp_dir):
    """Test that _check_path blocks parent directory traversal."""
    python_tools = PythonTools(base_dir=temp_dir)

    # Attempting to escape via ..
    safe, path = python_tools._check_path("../escape.py", python_tools.base_dir, python_tools.restrict_to_base_dir)
    assert not safe

    # Multiple levels of escape
    safe, path = python_tools._check_path("../../escape.py", python_tools.base_dir, python_tools.restrict_to_base_dir)
    assert not safe

    # Sneaky escape via subdir
    safe, path = python_tools._check_path(
        "subdir/../../escape.py", python_tools.base_dir, python_tools.restrict_to_base_dir
    )
    assert not safe


def test_save_to_file_blocks_path_traversal(temp_dir):
    """Test that save_to_file_and_run blocks path traversal attempts."""
    python_tools = PythonTools(base_dir=temp_dir)

    result = python_tools.save_to_file_and_run("../malicious.py", "x = 1")
    assert "outside the allowed base directory" in result


def test_read_file_blocks_path_traversal(temp_dir):
    """Test that read_file blocks path traversal attempts."""
    python_tools = PythonTools(base_dir=temp_dir)

    result = python_tools.read_file("../../../etc/passwd")
    assert "Error reading file" in result


def test_run_python_file_blocks_path_traversal(temp_dir):
    """Test that run_python_file_return_variable blocks path traversal attempts."""
    python_tools = PythonTools(base_dir=temp_dir)

    result = python_tools.run_python_file_return_variable("../malicious.py")
    assert "outside the allowed base directory" in result

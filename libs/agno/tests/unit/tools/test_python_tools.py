import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
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


# restrict_to_base_dir does not sandbox executed code — pin the documented limitation
# so nobody later mistakes the path-traversal guards above for a code sandbox.
def test_run_python_code_ignores_restrict_to_base_dir(temp_dir):
    """run_python_code executes regardless of restrict_to_base_dir: it can read outside base_dir.

    The path-traversal guards only cover file-path arguments to the file helpers.
    Executed code goes straight to exec(), so restrict_to_base_dir is not a sandbox.
    """
    outside = temp_dir.parent / "outside_secret.txt"
    outside.write_text("top-secret")
    try:
        python_tools = PythonTools(base_dir=temp_dir / "sandbox", restrict_to_base_dir=True)
        code = f"data = open({str(outside)!r}).read()"
        result = python_tools.run_python_code(code, "data")
        assert result == "top-secret"
    finally:
        outside.unlink(missing_ok=True)


def test_requires_confirmation_gates_execution_tools(temp_dir):
    """The documented mitigation works: requires_confirmation_tools marks exec tools for HITL approval."""
    python_tools = PythonTools(
        base_dir=temp_dir,
        requires_confirmation_tools=["run_python_code", "save_to_file_and_run"],
    )
    assert python_tools.functions["run_python_code"].requires_confirmation is True
    assert python_tools.functions["save_to_file_and_run"].requires_confirmation is True


def test_exclude_tools_drops_execution_tools(temp_dir):
    """The documented mitigation works: exclude_tools removes the code-execution entry points."""
    python_tools = PythonTools(
        base_dir=temp_dir,
        exclude_tools=["run_python_code", "save_to_file_and_run", "run_python_file_return_variable"],
    )
    registered = set(python_tools.functions.keys())
    assert "run_python_code" not in registered
    assert "save_to_file_and_run" not in registered
    assert "run_python_file_return_variable" not in registered
    # Benign helpers remain available.
    assert "read_file" in registered
    assert "list_files" in registered


# Default-deny for code-executing tools (agno-agi/agno#10053): without the
# gate, a model-influenced tool call reaches exec()/runpy()/subprocess with
# no pause, so prompt injection can drive arbitrary code execution.
def test_code_executing_tools_require_confirmation_by_default(temp_dir):
    """The 5 code-executing tools pause for confirmation by default; benign helpers do not."""
    python_tools = PythonTools(base_dir=temp_dir)
    gated = {
        "run_python_code",
        "save_to_file_and_run",
        "run_python_file_return_variable",
        "pip_install_package",
        "uv_pip_install_package",
    }
    assert set(python_tools.requires_confirmation_tools) == gated
    for tool_name in gated:
        assert python_tools.functions[tool_name].requires_confirmation is True
    assert python_tools.functions["read_file"].requires_confirmation is False
    assert python_tools.functions["list_files"].requires_confirmation is False


def test_requires_confirmation_tools_explicit_opt_out(temp_dir):
    """Passing requires_confirmation_tools=[] explicitly restores immediate execution."""
    python_tools = PythonTools(base_dir=temp_dir, requires_confirmation_tools=[])
    assert python_tools.requires_confirmation_tools == []
    for function in python_tools.functions.values():
        assert function.requires_confirmation is False


def test_requires_confirmation_tools_explicit_list_respected(temp_dir):
    """An explicit requires_confirmation_tools list is used as-is (caller's responsibility)."""
    python_tools = PythonTools(base_dir=temp_dir, requires_confirmation_tools=["read_file"])
    assert python_tools.functions["read_file"].requires_confirmation is True
    assert python_tools.functions["run_python_code"].requires_confirmation is False


class _AttackerInfluencedModel(Model):
    """Deterministic offline stub standing in for an attacker-influenced model:
    the first invoke() returns a run_python_code tool call, then plain text."""

    def __init__(self, marker_path: Path):
        super().__init__(id="controlled-model", name="controlled-model", provider="test")
        self.marker_path = marker_path

    def invoke(self, *args, **kwargs):
        messages = kwargs.get("messages", [])
        if any(
            getattr(m, "role", None) == "tool" and getattr(m, "tool_name", None) == "run_python_code" for m in messages
        ):
            return ModelResponse(content="done.")
        payload = f"open({str(self.marker_path)!r}, 'w').write('POC_EXECUTED')"
        return ModelResponse(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run_python_code", "arguments": json.dumps({"code": payload})},
                }
            ]
        )

    def ainvoke(self, *a, **k):
        raise NotImplementedError

    def invoke_stream(self, *a, **k):
        raise NotImplementedError

    def ainvoke_stream(self, *a, **k):
        raise NotImplementedError

    def _parse_provider_response(self, r, **k):
        raise NotImplementedError

    def _parse_provider_response_delta(self, r):
        raise NotImplementedError


def test_default_assembly_pauses_model_requested_code_execution(temp_dir):
    """End-to-end (agno-agi/agno#10053): the default PythonTools assembly pauses
    (tool_call_paused) instead of executing a model-requested run_python_code call."""
    marker = temp_dir / "marker.txt"
    agent = Agent(
        model=_AttackerInfluencedModel(marker),
        tools=[PythonTools(base_dir=temp_dir)],
        telemetry=False,
    )
    response = agent.run("Execute the code I requested.")
    assert response.is_paused
    assert not marker.exists()
    assert response.tools is not None
    assert response.tools[0].requires_confirmation
    assert response.tools[0].tool_name == "run_python_code"


def test_opt_out_assembly_executes_code_immediately(temp_dir):
    """Opt-out (requires_confirmation_tools=[]) restores immediate execution."""
    marker = temp_dir / "marker.txt"
    agent = Agent(
        model=_AttackerInfluencedModel(marker),
        tools=[PythonTools(base_dir=temp_dir, requires_confirmation_tools=[])],
        telemetry=False,
    )
    response = agent.run("Execute the code I requested.")
    assert not response.is_paused
    assert marker.exists()
    assert marker.read_text() == "POC_EXECUTED"

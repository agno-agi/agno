"""Unit tests for the SuperserveTools toolkit.

The `superserve` SDK is mocked at import time so these tests run without the
package installed and without any network access or credentials.
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock the superserve SDK before importing the toolkit so the guarded import
# succeeds without the package installed. Keep a module reference so per-test
# patches use patch.object (robust against sys.modules restoration).
with patch.dict(sys.modules, {"superserve": MagicMock()}):
    import agno.tools.superserve as superserve_module
    from agno.tools.superserve import SESSION_STATE_SANDBOX_ID, SuperserveTools

TEST_API_KEY = "ss_live_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _command_result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.exit_code = exit_code
    return result


def _sandbox_info(sandbox_id: str = "sbx-123") -> MagicMock:
    info = MagicMock()
    info.id = sandbox_id
    info.name = "agno-test"
    info.status.value = "active"
    info.metadata = {}
    return info


def _sync_sandbox(sandbox_id: str = "sbx-123") -> MagicMock:
    sandbox = MagicMock()
    sandbox.id = sandbox_id
    sandbox.commands.run.return_value = _command_result(stdout="hello world", exit_code=0)
    sandbox.files.read_text.return_value = "file contents"
    sandbox.files.download_dir.return_value = b"PK\x03\x04zip-bytes"
    sandbox.get_info.return_value = _sandbox_info(sandbox_id)
    return sandbox


def _async_sandbox(sandbox_id: str = "sbx-async") -> MagicMock:
    sandbox = MagicMock()
    sandbox.id = sandbox_id
    sandbox.commands.run = AsyncMock(return_value=_command_result(stdout="hello world", exit_code=0))
    sandbox.files.write = AsyncMock()
    sandbox.files.read_text = AsyncMock(return_value="file contents")
    sandbox.files.download_dir = AsyncMock(return_value=b"PK\x03\x04zip-bytes")
    sandbox.get_info = AsyncMock(return_value=_sandbox_info(sandbox_id))
    sandbox.kill = AsyncMock()
    sandbox.pause = AsyncMock()
    sandbox.resume = AsyncMock()
    sandbox.attach_secret = AsyncMock()
    sandbox.detach_secret = AsyncMock()
    return sandbox


@pytest.fixture
def agent() -> MagicMock:
    """An agent stub with a real dict session_state (so persistence logic works)."""
    a = MagicMock()
    a.session_state = {}
    return a


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
def test_init_with_api_key():
    tools = SuperserveTools(api_key=TEST_API_KEY)
    assert tools.api_key == TEST_API_KEY


def test_init_with_env_var(monkeypatch):
    monkeypatch.setenv("SUPERSERVE_API_KEY", "ss_live_env")
    tools = SuperserveTools()
    assert tools.api_key == "ss_live_env"


def test_init_without_api_key_raises(monkeypatch):
    monkeypatch.delenv("SUPERSERVE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPERSERVE_API_KEY not set"):
        SuperserveTools()


# ---------------------------------------------------------------------------
# Tool registration (sync + async, opt-in gating, include/exclude)
# ---------------------------------------------------------------------------
CORE_TOOLS = {
    "run_python_code",
    "run_command",
    "create_file",
    "read_file",
    "list_files",
    "delete_file",
    "download_directory",
    "get_sandbox_info",
    "list_sandboxes",
    "shutdown_sandbox",
}


def test_default_tools_registered():
    tools = SuperserveTools(api_key=TEST_API_KEY)
    names = set(tools.functions.keys())
    assert CORE_TOOLS.issubset(names)
    # Opt-in extras are off by default.
    assert "pause_sandbox" not in names
    assert "resume_sandbox" not in names
    assert "attach_secret" not in names
    assert "detach_secret" not in names


def test_async_variants_registered():
    """Every sync tool has a matching async variant under the same name."""
    tools = SuperserveTools(api_key=TEST_API_KEY)
    assert CORE_TOOLS.issubset(set(tools.async_functions.keys()))


def test_lifecycle_tools_opt_in():
    tools = SuperserveTools(api_key=TEST_API_KEY, enable_pause_sandbox=True, enable_resume_sandbox=True)
    names = set(tools.functions.keys())
    assert "pause_sandbox" in names
    assert "resume_sandbox" in names
    assert "pause_sandbox" in tools.async_functions
    assert "resume_sandbox" in tools.async_functions


def test_secret_tools_opt_in():
    tools = SuperserveTools(api_key=TEST_API_KEY, enable_attach_secret=True, enable_detach_secret=True)
    names = set(tools.functions.keys())
    assert "attach_secret" in names
    assert "detach_secret" in names


def test_all_flag_enables_every_tool():
    tools = SuperserveTools(api_key=TEST_API_KEY, all=True)
    names = set(tools.functions.keys())
    assert CORE_TOOLS.issubset(names)
    assert {"pause_sandbox", "resume_sandbox", "attach_secret", "detach_secret"}.issubset(names)


def test_disable_individual_core_tool():
    tools = SuperserveTools(api_key=TEST_API_KEY, enable_shutdown_sandbox=False)
    names = set(tools.functions.keys())
    assert "shutdown_sandbox" not in names
    assert "run_command" in names


def test_include_tools_filter():
    tools = SuperserveTools(api_key=TEST_API_KEY, include_tools=["run_command", "read_file"])
    names = set(tools.functions.keys())
    assert names == {"run_command", "read_file"}


def test_exclude_tools_filter():
    tools = SuperserveTools(api_key=TEST_API_KEY, exclude_tools=["shutdown_sandbox"])
    names = set(tools.functions.keys())
    assert "shutdown_sandbox" not in names
    assert "run_command" in names


# ---------------------------------------------------------------------------
# Sync tool behavior
# ---------------------------------------------------------------------------
def test_run_command(agent):
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.run_command(agent, "echo hello")

    sandbox.commands.run.assert_called_once_with("echo hello", timeout_seconds=tools.command_timeout)
    assert "STDOUT:\nhello world" in result
    assert "Exit code: 0" in result


def test_run_python_code_writes_then_executes(agent):
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.run_python_code(agent, "print('hi')")

    # Code is written to a temp file, then executed with python3.
    assert sandbox.files.write.call_count == 1
    written_path, written_code = sandbox.files.write.call_args[0]
    assert written_path.startswith("/tmp/agno_run_")
    assert written_path.endswith(".py")
    assert "print('hi')" in written_code
    run_cmd = sandbox.commands.run.call_args[0][0]
    assert run_cmd.startswith("python3 ")
    assert "STDOUT:\nhello world" in result


def test_run_python_code_normalizes_keywords(agent):
    """prepare_python_code should fix lowercase True/False/None before writing."""
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        tools.run_python_code(agent, "x = true")

    _, written_code = sandbox.files.write.call_args[0]
    assert "True" in written_code
    assert "true" not in written_code


def test_create_file(agent):
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.create_file(agent, "/app/main.py", "print(1)")

    sandbox.files.write.assert_called_once_with("/app/main.py", "print(1)")
    assert "/app/main.py" in result


def test_read_file(agent):
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.read_file(agent, "/app/main.py")

    sandbox.files.read_text.assert_called_once_with("/app/main.py")
    assert result == "file contents"


def test_list_files_uses_ls(agent):
    sandbox = _sync_sandbox()
    sandbox.commands.run.return_value = _command_result(stdout="total 0\ndrwxr-xr-x ...", exit_code=0)
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.list_files(agent, "/app")

    assert sandbox.commands.run.call_args[0][0].startswith("ls -la ")
    assert "Contents of /app:" in result


def test_delete_file_uses_rm(agent):
    sandbox = _sync_sandbox()
    sandbox.commands.run.return_value = _command_result(exit_code=0)
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.delete_file(agent, "/app/old.py")

    assert sandbox.commands.run.call_args[0][0].startswith("rm -rf ")
    assert "Deleted: /app/old.py" in result


def test_get_sandbox_info(agent):
    sandbox = _sync_sandbox("sbx-info")
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.get_sandbox_info(agent)

    payload = json.loads(result)
    assert payload["id"] == "sbx-info"
    assert payload["status"] == "active"


def test_list_sandboxes():
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.list.return_value = [_sandbox_info("sbx-1"), _sandbox_info("sbx-2")]
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.list_sandboxes()

    payload = json.loads(result)
    assert {item["id"] for item in payload} == {"sbx-1", "sbx-2"}


# ---------------------------------------------------------------------------
# Lifecycle: reuse, connect, shutdown
# ---------------------------------------------------------------------------
def test_sandbox_created_once_and_reused(agent):
    sandbox = _sync_sandbox()
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        tools.run_command(agent, "echo 1")
        tools.run_command(agent, "echo 2")

    assert mock_cls.create.call_count == 1
    assert agent.session_state[SESSION_STATE_SANDBOX_ID] == sandbox.id


def test_connect_to_existing_sandbox_id(agent):
    sandbox = _sync_sandbox("sbx-existing")
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.connect.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY, sandbox_id="sbx-existing")
        tools.run_command(agent, "echo 1")

    mock_cls.connect.assert_called_once_with("sbx-existing", api_key=TEST_API_KEY, base_url=None)
    mock_cls.create.assert_not_called()


def test_shutdown_sandbox_clears_state(agent):
    agent.session_state[SESSION_STATE_SANDBOX_ID] = "sbx-kill"
    sandbox = _sync_sandbox("sbx-kill")
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.connect.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.shutdown_sandbox(agent)

    sandbox.kill.assert_called_once()
    assert SESSION_STATE_SANDBOX_ID not in agent.session_state
    assert "shut down" in result


def test_shutdown_without_active_sandbox(agent):
    tools = SuperserveTools(api_key=TEST_API_KEY)
    result = tools.shutdown_sandbox(agent)
    assert "No active sandbox" in result


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
def test_error_returns_json_envelope(agent):
    sandbox = _sync_sandbox()
    sandbox.commands.run.side_effect = RuntimeError("boom")
    with patch.object(superserve_module, "Sandbox") as mock_cls:
        mock_cls.create.return_value = sandbox
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = tools.run_command(agent, "false")

    payload = json.loads(result)
    assert payload["status"] == "error"
    assert "boom" in payload["message"]


# ---------------------------------------------------------------------------
# Async tool behavior
# ---------------------------------------------------------------------------
async def test_arun_command(agent):
    sandbox = _async_sandbox()
    with patch.object(superserve_module, "AsyncSandbox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=sandbox)
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = await tools.arun_command(agent, "echo hello")

    sandbox.commands.run.assert_awaited_once_with("echo hello", timeout_seconds=tools.command_timeout)
    assert "STDOUT:\nhello world" in result


async def test_arun_python_code(agent):
    sandbox = _async_sandbox()
    with patch.object(superserve_module, "AsyncSandbox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=sandbox)
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = await tools.arun_python_code(agent, "print('hi')")

    sandbox.files.write.assert_awaited_once()
    sandbox.commands.run.assert_awaited_once()
    assert "STDOUT:\nhello world" in result


async def test_ashutdown_sandbox(agent):
    agent.session_state[SESSION_STATE_SANDBOX_ID] = "sbx-async"
    sandbox = _async_sandbox("sbx-async")
    with patch.object(superserve_module, "AsyncSandbox") as mock_cls:
        mock_cls.connect = AsyncMock(return_value=sandbox)
        tools = SuperserveTools(api_key=TEST_API_KEY)
        result = await tools.ashutdown_sandbox(agent)

    sandbox.kill.assert_awaited_once()
    assert SESSION_STATE_SANDBOX_ID not in agent.session_state
    assert "shut down" in result

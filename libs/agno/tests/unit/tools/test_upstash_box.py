"""Unit tests for the UpstashBoxTools toolkit.

The `upstash_box` SDK is mocked at import time so these tests run without the
package installed and without any network access or credentials. `BoxError` is a
real exception class, because the toolkit catches it.
"""

import asyncio
import importlib.util
import json
import sys
import threading
import time
import types
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext


class _BoxError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_sdk = types.ModuleType("upstash_box")
_sdk.Box = MagicMock()  # type: ignore[attr-defined]
_sdk.AsyncBox = MagicMock()  # type: ignore[attr-defined]
_sdk.BoxError = _BoxError  # type: ignore[attr-defined]


def _load_toolkit_against_fake_sdk() -> types.ModuleType:
    """Build a private copy of the toolkit module bound to the fake SDK.

    A plain import would reuse `agno.tools.upstash_box` if another test file (e.g. the
    live integration tests) already imported it against the real SDK; the toolkit
    would then catch the real `BoxError` instead of the fake one these mocks raise.
    The copy is never registered in sys.modules, so the real module stays intact for
    the HTTP transport and integration tests.
    """
    spec = importlib.util.find_spec("agno.tools.upstash_box")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"upstash_box": _sdk}):
        spec.loader.exec_module(module)
    return module


# Per-test patches use patch.object on this module reference.
box_module = _load_toolkit_against_fake_sdk()
DEFAULT_LABEL = box_module.DEFAULT_LABEL
SESSION_STATE_BOX_ID = box_module.SESSION_STATE_BOX_ID
WORKSPACE = box_module.WORKSPACE
UpstashBoxTools = box_module.UpstashBoxTools

TEST_API_KEY = "box_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    run = MagicMock()
    run.stdout = stdout
    run.stderr = stderr
    run.exit_code = exit_code
    return run


def _entry(name: str, is_dir: bool = False, size: int = 0) -> MagicMock:
    entry = MagicMock()
    entry.name = name
    entry.is_dir = is_dir
    entry.size = size
    return entry


def _sync_box(box_id: str = "box-123") -> MagicMock:
    box = MagicMock()
    box.id = box_id
    box.size = "small"
    box.keep_alive = False
    box.exec.command.return_value = _run(stdout="hello world")
    box.exec.code.return_value = _run(stdout="42")
    box.files.read.return_value = "file contents"
    box.files.list.return_value = [_entry("main.py", size=12), _entry("src", is_dir=True)]
    box.get_status.return_value = {"status": "idle"}
    box.get_public_url.return_value = MagicMock(url="https://box-123-8000.preview.box.upstash.com")
    box.snapshot.return_value = MagicMock(id="snap-1", status="ready")
    box.snapshot.return_value.name = "checkpoint"
    return box


def _async_box(box_id: str = "box-async") -> MagicMock:
    box = MagicMock()
    box.id = box_id
    box.size = "small"
    box.keep_alive = False
    box.exec.command = AsyncMock(return_value=_run(stdout="hello world"))
    box.exec.code = AsyncMock(return_value=_run(stdout="42"))
    box.files.write = AsyncMock()
    box.files.read = AsyncMock(return_value="file contents")
    box.files.list = AsyncMock(return_value=[_entry("main.py", size=12)])
    box.files.remove = AsyncMock()
    box.get_status = AsyncMock(return_value={"status": "idle"})
    box.get_public_url = AsyncMock(return_value=MagicMock(url="https://box-async-8000.preview.box.upstash.com"))
    box.delete = AsyncMock()
    box.aclose = AsyncMock()
    box.pause = AsyncMock()
    box.resume = AsyncMock()
    return box


@pytest.fixture
def run_context() -> RunContext:
    """The run context agno injects into tools; its session_state is what gets persisted."""
    return RunContext(run_id="run-1", session_id="session-1", session_state={})


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("UPSTASH_BOX_API_KEY", raising=False)
    monkeypatch.delenv("UPSTASH_BOX_BASE_URL", raising=False)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
def test_init_with_api_key():
    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    assert tools.api_key == TEST_API_KEY


def test_init_with_env_vars(monkeypatch):
    monkeypatch.setenv("UPSTASH_BOX_API_KEY", "box_env")
    monkeypatch.setenv("UPSTASH_BOX_BASE_URL", "https://example.box")
    tools = UpstashBoxTools()
    assert tools.api_key == "box_env"
    assert tools.base_url == "https://example.box"


def test_init_without_api_key_raises():
    with pytest.raises(ValueError, match="UPSTASH_BOX_API_KEY not set"):
        UpstashBoxTools()


def test_agno_label_always_added_once():
    assert UpstashBoxTools(api_key=TEST_API_KEY).labels == [DEFAULT_LABEL]
    tools = UpstashBoxTools(api_key=TEST_API_KEY, labels=["team-a", DEFAULT_LABEL])
    assert tools.labels == [DEFAULT_LABEL, "team-a"]


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
    "get_box_info",
    "list_boxes",
    "shutdown_box",
    "shutdown_box_by_id",
    "get_public_url",
}
LIFECYCLE_TOOLS = {"pause_box", "resume_box", "snapshot_box"}


def test_default_tools_registered():
    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    names = set(tools.functions.keys())
    assert names == CORE_TOOLS


def test_async_variants_registered():
    """Every sync tool has a matching async variant under the same name."""
    tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
    assert set(tools.async_functions.keys()) == set(tools.functions.keys())


def test_lifecycle_tools_opt_in():
    tools = UpstashBoxTools(
        api_key=TEST_API_KEY, enable_pause_box=True, enable_resume_box=True, enable_snapshot_box=True
    )
    assert LIFECYCLE_TOOLS.issubset(set(tools.functions.keys()))
    assert LIFECYCLE_TOOLS.issubset(set(tools.async_functions.keys()))


def test_all_flag_enables_every_tool():
    tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
    assert set(tools.functions.keys()) == CORE_TOOLS | LIFECYCLE_TOOLS


def test_disable_individual_core_tool():
    tools = UpstashBoxTools(api_key=TEST_API_KEY, enable_shutdown_box_by_id=False)
    names = set(tools.functions.keys())
    assert "shutdown_box_by_id" not in names
    assert "run_command" in names


def test_include_and_exclude_tools_filters():
    included = UpstashBoxTools(api_key=TEST_API_KEY, include_tools=["run_command", "read_file"])
    assert set(included.functions.keys()) == {"run_command", "read_file"}
    excluded = UpstashBoxTools(api_key=TEST_API_KEY, exclude_tools=["shutdown_box"])
    assert "shutdown_box" not in excluded.functions


# ---------------------------------------------------------------------------
# Box lifecycle: create, reuse, connect, recover
# ---------------------------------------------------------------------------
def test_box_created_once_with_defaults_and_reused(run_context):
    box = _sync_box()
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.run_command(run_context, "echo 1")
        tools.run_command(run_context, "echo 2")

    mock_cls.create.assert_called_once()
    kwargs = mock_cls.create.call_args.kwargs
    assert kwargs["api_key"] == TEST_API_KEY
    assert kwargs["runtime"] == "python"
    assert kwargs["labels"] == [DEFAULT_LABEL]
    assert kwargs["name"].startswith("agno-")
    assert "keep_alive" not in kwargs and "size" not in kwargs and "env" not in kwargs
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-123"


def test_create_options_forwarded(run_context):
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = _sync_box()
        tools = UpstashBoxTools(
            api_key=TEST_API_KEY,
            base_url="https://example.box",
            runtime="node",
            size="medium",
            keep_alive=True,
            env_vars={"FOO": "bar"},
        )
        tools.run_command(run_context, "ls")

    kwargs = mock_cls.create.call_args.kwargs
    assert kwargs["base_url"] == "https://example.box"
    assert kwargs["runtime"] == "node"
    assert kwargs["size"] == "medium"
    assert kwargs["keep_alive"] is True
    assert kwargs["env"] == {"FOO": "bar"}


def test_reconnects_to_box_in_session_state(run_context):
    run_context.session_state[SESSION_STATE_BOX_ID] = "box-saved"
    box = _sync_box("box-saved")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.run_command(run_context, "ls")

    mock_cls.get.assert_called_once_with("box-saved", api_key=TEST_API_KEY)
    box.get_status.assert_called_once()  # verifies the box still exists
    mock_cls.create.assert_not_called()


def test_connects_to_explicit_box_id(run_context):
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = _sync_box("box-explicit")
        tools = UpstashBoxTools(api_key=TEST_API_KEY, box_id="box-explicit")
        tools.run_command(run_context, "ls")

    mock_cls.get.assert_called_once_with("box-explicit", api_key=TEST_API_KEY)
    mock_cls.create.assert_not_called()


def test_box_deleted_outside_agent_is_replaced(run_context):
    # Looking up a deleted box succeeds; its status call returns 404.
    run_context.session_state[SESSION_STATE_BOX_ID] = "box-gone"
    gone = _sync_box("box-gone")
    gone.get_status.side_effect = _BoxError("Box has been deleted", 404)
    fresh = _sync_box("box-fresh")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = gone
        mock_cls.create.return_value = fresh
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        result = tools.run_command(run_context, "echo hi")

    assert "hello world" in result
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-fresh"


def test_explicit_box_id_that_is_gone_is_an_error(run_context):
    gone = _sync_box("box-gone")
    gone.get_status.side_effect = _BoxError("Box has been deleted", 404)
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = gone
        tools = UpstashBoxTools(api_key=TEST_API_KEY, box_id="box-gone")
        result = tools.run_command(run_context, "echo hi")

    mock_cls.create.assert_not_called()
    assert json.loads(result)["status"] == "error"
    assert "Box has been deleted" in json.loads(result)["message"]


def test_other_connect_errors_are_not_swallowed(run_context):
    run_context.session_state[SESSION_STATE_BOX_ID] = "box-saved"
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.side_effect = _BoxError("Invalid box API key", 401)
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        result = tools.run_command(run_context, "ls")

    mock_cls.create.assert_not_called()
    assert "Invalid box API key" in json.loads(result)["message"]


def test_not_persistent_skips_session_state(run_context):
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = _sync_box()
        tools = UpstashBoxTools(api_key=TEST_API_KEY, persistent=False)
        tools.run_command(run_context, "ls")

    assert SESSION_STATE_BOX_ID not in run_context.session_state


# ---------------------------------------------------------------------------
# Sync tool behavior
# ---------------------------------------------------------------------------
@pytest.fixture
def box_tools():
    """A toolkit wired to a mocked sync box."""
    box = _sync_box()
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        yield UpstashBoxTools(api_key=TEST_API_KEY, all=True), box, mock_cls


def test_run_command(run_context, box_tools):
    tools, box, _ = box_tools
    result = tools.run_command(run_context, "echo hello")
    box.exec.command.assert_called_once_with("echo hello")
    assert result == "STDOUT:\nhello world\nExit code: 0"


def test_run_command_reports_stderr_and_exit_code(run_context, box_tools):
    tools, box, _ = box_tools
    box.exec.command.return_value = _run(stderr="not found", exit_code=127)
    result = tools.run_command(run_context, "nope")
    assert result == "STDERR:\nnot found\nExit code: 127"


def test_run_python_code_uses_code_endpoint(run_context, box_tools):
    tools, box, _ = box_tools
    result = tools.run_python_code(run_context, "x = true\nprint(42)")
    # LLM-style lowercase keywords are normalized before running.
    box.exec.code.assert_called_once_with(code="x = True\nprint(42)", lang="python")
    assert "STDOUT:\n42" in result


def test_command_timeout_wraps_shell_command(run_context):
    with patch.object(box_module, "Box") as mock_cls:
        box = _sync_box()
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY, command_timeout=30)
        tools.run_command(run_context, "sleep 60 && echo 'done'")

    box.exec.command.assert_called_once_with("timeout 30 sh -c 'sleep 60 && echo '\"'\"'done'\"'\"''")


def test_command_timeout_runs_python_as_timed_script(run_context):
    # The Box code endpoint takes no timeout, so timed code runs as a script under `timeout`.
    with patch.object(box_module, "Box") as mock_cls:
        box = _sync_box()
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY, command_timeout=10)
        tools.run_python_code(run_context, "print(false)")

    box.exec.code.assert_not_called()
    path = box.files.write.call_args.kwargs["path"]
    assert path.startswith("/tmp/agno_run_") and path.endswith(".py")
    assert box.files.write.call_args.kwargs["content"] == "print(False)"
    box.exec.command.assert_called_once_with(f"timeout 10 sh -c 'python3 {path}'")


def test_create_file(run_context, box_tools):
    tools, box, _ = box_tools
    assert tools.create_file(run_context, "src/app.py", "print(1)") == "File written: src/app.py"
    box.files.write.assert_called_once_with(path="src/app.py", content="print(1)")


def test_read_file(run_context, box_tools):
    tools, box, _ = box_tools
    assert tools.read_file(run_context, "src/app.py") == "file contents"
    box.files.read.assert_called_once_with("src/app.py")


def test_list_files_defaults_to_workspace_and_sorts_dirs_first(run_context, box_tools):
    tools, box, _ = box_tools
    result = tools.list_files(run_context)
    box.files.list.assert_called_once_with(WORKSPACE)
    assert result == f"Contents of {WORKSPACE}:\ndir   src/\nfile  main.py (12 bytes)"


def test_list_files_empty_directory(run_context, box_tools):
    tools, box, _ = box_tools
    box.files.list.return_value = []
    assert tools.list_files(run_context, "/tmp/empty") == "/tmp/empty is empty."


def test_delete_file_is_recursive(run_context, box_tools):
    tools, box, _ = box_tools
    assert tools.delete_file(run_context, "build") == "Deleted: build"
    box.files.remove.assert_called_once_with("build", recursive=True)


def test_get_box_info(run_context, box_tools):
    tools, _, _ = box_tools
    info = json.loads(tools.get_box_info(run_context))
    assert info == {"id": "box-123", "status": "idle", "size": "small", "keep_alive": False}


def test_list_boxes_scoped_to_agno_label(box_tools):
    tools, _, mock_cls = box_tools
    listed = MagicMock(id="box-1", status="idle", runtime="python", labels=["agno"])
    listed.name = "agno-abc"
    mock_cls.list.return_value = [listed]
    result = json.loads(tools.list_boxes())
    mock_cls.list.assert_called_once_with(label=DEFAULT_LABEL, api_key=TEST_API_KEY)
    assert result == [{"id": "box-1", "name": "agno-abc", "status": "idle", "runtime": "python", "labels": ["agno"]}]


def test_get_public_url(run_context, box_tools):
    tools, box, _ = box_tools
    assert tools.get_public_url(run_context, 8000) == "https://box-123-8000.preview.box.upstash.com"
    box.get_public_url.assert_called_once_with(8000)


def test_get_public_url_without_url_is_an_error(run_context, box_tools):
    tools, box, _ = box_tools
    box.get_public_url.return_value = MagicMock(url=None)
    assert json.loads(tools.get_public_url(run_context, 8000))["status"] == "error"


def test_shutdown_box_deletes_and_clears_state(run_context, box_tools):
    tools, box, mock_cls = box_tools
    tools.run_command(run_context, "ls")
    assert tools.shutdown_box(run_context) == "Box box-123 shut down."
    # Deletes through its own short-lived client (not the cached one, which another
    # shutdown may close), never the static bulk delete with its 5-second timeout.
    mock_cls.get.assert_called_once_with("box-123", api_key=TEST_API_KEY)
    mock_cls.get.return_value.delete.assert_called_once()
    mock_cls.get.return_value.close.assert_called_once()
    mock_cls.delete_boxes.assert_not_called()
    box.delete.assert_not_called()
    box.close.assert_called_once()
    assert SESSION_STATE_BOX_ID not in run_context.session_state
    assert not tools._boxes


def test_shutdown_without_active_box(run_context, box_tools):
    tools, box, _ = box_tools
    assert tools.shutdown_box(run_context) == "No active box to shut down."
    box.delete.assert_not_called()


def test_shutdown_box_by_id_clears_active_box(run_context, box_tools):
    tools, _, mock_cls = box_tools
    tools.run_command(run_context, "ls")
    assert tools.shutdown_box_by_id(run_context, "box-123") == "Box box-123 shut down."
    mock_cls.get.return_value.delete.assert_called_once()
    assert not tools._boxes
    assert SESSION_STATE_BOX_ID not in run_context.session_state


def test_shutdown_box_by_id_keeps_unrelated_box(run_context, box_tools):
    tools, _, _ = box_tools
    tools.run_command(run_context, "ls")
    tools.shutdown_box_by_id(run_context, "box-other")
    assert tools._boxes
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-123"


def test_pause_resume_snapshot(run_context, box_tools):
    tools, box, _ = box_tools
    tools.run_command(run_context, "ls")
    assert tools.pause_box(run_context) == "Box box-123 paused."
    assert tools.resume_box(run_context) == "Box box-123 resumed."
    snapshot = json.loads(tools.snapshot_box(run_context, "checkpoint"))
    box.snapshot.assert_called_once_with(name="checkpoint")
    assert snapshot == {"id": "snap-1", "name": "checkpoint", "status": "ready"}


def test_errors_return_json_envelope(run_context, box_tools):
    tools, box, _ = box_tools
    box.files.read.side_effect = _BoxError("file not found: /workspace/home/x", 404)
    payload = json.loads(tools.read_file(run_context, "x"))
    assert payload == {"status": "error", "message": "Error reading file: file not found: /workspace/home/x"}


# ---------------------------------------------------------------------------
# Async tool behavior
# ---------------------------------------------------------------------------
@pytest.fixture
def async_box_tools():
    box = _async_box()
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=box)
        mock_cls.get = AsyncMock(return_value=box)
        mock_cls.list = AsyncMock(return_value=[])
        mock_cls.delete_boxes = AsyncMock()
        yield UpstashBoxTools(api_key=TEST_API_KEY, all=True), box, mock_cls


async def test_arun_command(run_context, async_box_tools):
    tools, box, mock_cls = async_box_tools
    result = await tools.arun_command(run_context, "echo hello")
    box.exec.command.assert_awaited_once_with("echo hello")
    assert "STDOUT:\nhello world" in result
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-async"


async def test_arun_python_code(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    result = await tools.arun_python_code(run_context, "print(42)")
    box.exec.code.assert_awaited_once_with(code="print(42)", lang="python")
    assert "STDOUT:\n42" in result


async def test_arun_python_code_with_timeout(run_context):
    box = _async_box()
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=box)
        tools = UpstashBoxTools(api_key=TEST_API_KEY, command_timeout=10)
        await tools.arun_python_code(run_context, "print(1)")

    box.exec.code.assert_not_called()
    path = box.files.write.call_args.kwargs["path"]
    box.exec.command.assert_awaited_once_with(f"timeout 10 sh -c 'python3 {path}'")


async def test_async_file_tools(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    assert await tools.acreate_file(run_context, "a.txt", "hi") == "File written: a.txt"
    assert await tools.aread_file(run_context, "a.txt") == "file contents"
    assert (await tools.alist_files(run_context)).startswith(f"Contents of {WORKSPACE}:")
    assert await tools.adelete_file(run_context, "a.txt") == "Deleted: a.txt"
    box.files.remove.assert_awaited_once_with("a.txt", recursive=True)


async def test_aget_box_info_and_public_url(run_context, async_box_tools):
    tools, _, _ = async_box_tools
    assert json.loads(await tools.aget_box_info(run_context))["status"] == "idle"
    assert await tools.aget_public_url(run_context, 8000) == "https://box-async-8000.preview.box.upstash.com"


async def test_alist_boxes(async_box_tools):
    tools, _, mock_cls = async_box_tools
    assert json.loads(await tools.alist_boxes()) == []
    mock_cls.list.assert_awaited_once_with(label=DEFAULT_LABEL, api_key=TEST_API_KEY)


async def test_async_box_deleted_outside_agent_is_replaced(run_context):
    run_context.session_state[SESSION_STATE_BOX_ID] = "box-gone"
    gone = _async_box("box-gone")
    gone.get_status = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    fresh = _async_box("box-fresh")
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.get = AsyncMock(return_value=gone)
        mock_cls.create = AsyncMock(return_value=fresh)
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        await tools.arun_command(run_context, "echo hi")

    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-fresh"


async def test_ashutdown_box(run_context, async_box_tools):
    tools, box, mock_cls = async_box_tools
    await tools.arun_command(run_context, "ls")
    deleter = _async_box("box-async")
    mock_cls.get = AsyncMock(return_value=deleter)
    assert await tools.ashutdown_box(run_context) == "Box box-async shut down."
    deleter.delete.assert_awaited_once()
    deleter.aclose.assert_awaited_once()
    mock_cls.delete_boxes.assert_not_awaited()
    box.delete.assert_not_awaited()
    box.aclose.assert_awaited_once()
    assert SESSION_STATE_BOX_ID not in run_context.session_state


async def test_ashutdown_box_by_id(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    await tools.arun_command(run_context, "ls")
    assert await tools.ashutdown_box_by_id(run_context, "box-async") == "Box box-async shut down."
    box.delete.assert_awaited_once()
    assert not tools._async_boxes


async def test_async_lifecycle_tools(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    await tools.arun_command(run_context, "ls")
    box.snapshot = AsyncMock(return_value=MagicMock(id="snap-1", status="ready"))
    box.snapshot.return_value.name = "cp"
    assert await tools.apause_box(run_context) == "Box box-async paused."
    assert await tools.aresume_box(run_context) == "Box box-async resumed."
    assert json.loads(await tools.asnapshot_box(run_context, "cp"))["id"] == "snap-1"


async def test_async_errors_return_json_envelope(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    box.exec.command = AsyncMock(side_effect=RuntimeError("boom"))
    payload = json.loads(await tools.arun_command(run_context, "ls"))
    assert payload["status"] == "error"
    assert "boom" in payload["message"]


# ---------------------------------------------------------------------------
# Session scoping, persistence, concurrency, and deleted-box recovery
# ---------------------------------------------------------------------------
class _ScriptedModel(Model):
    """Offline model that asks for one tool call, then answers."""

    def __init__(self, tool_name: str, arguments: dict) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0

    def __deepcopy__(self, memo):
        return self

    def _respond(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": self.tool_name, "arguments": json.dumps(self.arguments)},
                    }
                ],
            )
        return ModelResponse(role="assistant", content="done")

    def invoke(self, *args, **kwargs):
        return self._respond()

    async def ainvoke(self, *args, **kwargs):
        return self._respond()

    def invoke_stream(self, *args, **kwargs):
        yield self._respond()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._respond()

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def test_box_id_is_saved_with_the_session_and_reused_by_a_new_agent():
    # The id must land in the run's session_state, which agno persists, not on the agent object.
    db = InMemoryDb()
    box = _sync_box("box-saved")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        mock_cls.get.return_value = box
        first = Agent(
            model=_ScriptedModel("run_command", {"command": "echo 1"}),
            tools=[UpstashBoxTools(api_key=TEST_API_KEY)],
            db=db,
            session_id="s1",
        )
        output = first.run("go")
        resumed = Agent(
            model=_ScriptedModel("run_command", {"command": "echo 2"}),
            tools=[UpstashBoxTools(api_key=TEST_API_KEY)],
            db=db,
            session_id="s1",
        )
        resumed.run("go")

    assert output.session_state == {SESSION_STATE_BOX_ID: "box-saved"}
    saved = db.get_session(session_id="s1", session_type="agent")
    assert saved.session_data["session_state"][SESSION_STATE_BOX_ID] == "box-saved"
    mock_cls.create.assert_called_once()
    mock_cls.get.assert_called_once_with("box-saved", api_key=TEST_API_KEY)


def test_sessions_sharing_a_toolkit_get_separate_boxes():
    box_a, box_b = _sync_box("box-a"), _sync_box("box-b")
    session_a = RunContext(run_id="r1", session_id="a", session_state={})
    session_b = RunContext(run_id="r2", session_id="b", session_state={})
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.side_effect = [box_a, box_b]
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.create_file(session_a, "secret.txt", "A's data")
        tools.read_file(session_b, "secret.txt")

    box_a.files.write.assert_called_once()
    box_a.files.read.assert_not_called()
    box_b.files.read.assert_called_once_with("secret.txt")
    assert session_a.session_state[SESSION_STATE_BOX_ID] == "box-a"
    assert session_b.session_state[SESSION_STATE_BOX_ID] == "box-b"


def test_sessions_get_separate_boxes_when_not_persistent():
    session_a = RunContext(run_id="r1", session_id="a", session_state={})
    session_b = RunContext(run_id="r2", session_id="b", session_state={})
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.side_effect = [_sync_box("box-a"), _sync_box("box-b")]
        tools = UpstashBoxTools(api_key=TEST_API_KEY, persistent=False)
        tools.run_command(session_a, "ls")
        tools.run_command(session_b, "ls")
        tools.run_command(session_a, "ls")

    assert mock_cls.create.call_count == 2
    assert session_a.session_state == {}


async def test_concurrent_first_async_calls_create_one_box(run_context):
    created = []

    async def slow_create(**kwargs):
        await asyncio.sleep(0.05)
        box = _async_box(f"box-{len(created) + 1}")
        created.append(box)
        return box

    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = slow_create
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        await asyncio.gather(
            tools.acreate_file(run_context, "x.txt", "x"),
            tools.acreate_file(run_context, "y.txt", "y"),
        )

    assert len(created) == 1
    assert created[0].files.write.await_count == 2
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-1"


def test_concurrent_first_sync_calls_create_one_box(run_context):
    created = []

    def slow_create(**kwargs):
        time.sleep(0.05)
        box = _sync_box(f"box-{len(created) + 1}")
        created.append(box)
        return box

    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.side_effect = slow_create
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        threads = [threading.Thread(target=tools.run_command, args=(run_context, "ls")) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(created) == 1


def test_cached_box_deleted_outside_agent_is_replaced(run_context):
    gone, fresh = _sync_box("box-gone"), _sync_box("box-fresh")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.side_effect = [gone, fresh]
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.run_command(run_context, "echo first")
        # The box is deleted elsewhere while this toolkit still holds a client for it.
        gone.exec.command.side_effect = _BoxError("Box has been deleted", 404)
        gone.get_status.side_effect = _BoxError("Box has been deleted", 404)
        result = tools.run_command(run_context, "echo second")

    assert "hello world" in result
    fresh.exec.command.assert_called_once_with("echo second")
    gone.close.assert_called_once()
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-fresh"


def test_missing_file_does_not_replace_the_box(run_context):
    # A missing file is also a 404, but the box itself still exists.
    box = _sync_box()
    box.files.read.side_effect = _BoxError("file not found: /workspace/home/nope.txt", 404)
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        result = tools.read_file(run_context, "nope.txt")

    mock_cls.create.assert_called_once()
    assert "file not found" in json.loads(result)["message"]
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-123"


def test_cached_explicit_box_deleted_is_an_error(run_context):
    box = _sync_box("box-explicit")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY, box_id="box-explicit")
        tools.run_command(run_context, "ls")
        box.exec.command.side_effect = _BoxError("Box has been deleted", 404)
        box.get_status.side_effect = _BoxError("Box has been deleted", 404)
        result = tools.run_command(run_context, "ls")

    mock_cls.create.assert_not_called()
    assert "Box box-explicit no longer exists" in json.loads(result)["message"]


async def test_async_cached_box_deleted_outside_agent_is_replaced(run_context):
    gone, fresh = _async_box("box-gone"), _async_box("box-fresh")
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(side_effect=[gone, fresh])
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        await tools.arun_command(run_context, "echo first")
        gone.exec.command = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
        gone.get_status = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
        result = await tools.arun_command(run_context, "echo second")

    assert "hello world" in result
    fresh.exec.command.assert_awaited_once_with("echo second")
    gone.aclose.assert_awaited_once()
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-fresh"


# ---------------------------------------------------------------------------
# Every run of a session, event loops, sync/async sharing, deleted-box shutdown
# ---------------------------------------------------------------------------
def test_every_run_of_a_session_gets_the_box_id():
    # Separate runs of one session have separate state dicts; each must carry the id.
    first = RunContext(run_id="r1", session_id="same", session_state={})
    second = RunContext(run_id="r2", session_id="same", session_state={})
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = _sync_box("box-1")
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.run_command(first, "a")
        tools.run_command(second, "b")

    mock_cls.create.assert_called_once()
    assert first.session_state[SESSION_STATE_BOX_ID] == "box-1"
    assert second.session_state[SESSION_STATE_BOX_ID] == "box-1"


async def test_every_async_run_of_a_session_gets_the_box_id():
    first = RunContext(run_id="r1", session_id="same", session_state={})
    second = RunContext(run_id="r2", session_id="same", session_state={})
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=_async_box("box-1"))
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        await asyncio.gather(tools.arun_command(first, "a"), tools.arun_command(second, "b"))

    assert mock_cls.create.await_count == 1
    assert first.session_state[SESSION_STATE_BOX_ID] == "box-1"
    assert second.session_state[SESSION_STATE_BOX_ID] == "box-1"


def test_repeated_agent_runs_keep_the_box_id_in_every_output():
    box = _sync_box("box-1")
    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        outputs = [
            Agent(model=_ScriptedModel("run_command", {"command": c}), tools=[tools], session_id="s").run("go")
            for c in ("echo 1", "echo 2")
        ]

    mock_cls.create.assert_called_once()
    assert [o.session_state[SESSION_STATE_BOX_ID] for o in outputs] == ["box-1", "box-1"]


def test_a_new_event_loop_reconnects_instead_of_reusing_another_loops_client():
    run_context = RunContext(run_id="r", session_id="s", session_state={})
    first, second = _async_box("box-1"), _async_box("box-1")
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(return_value=first)
        mock_cls.get = AsyncMock(return_value=second)
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        asyncio.run(tools.arun_command(run_context, "a"))
        asyncio.run(tools.arun_command(run_context, "b"))

    mock_cls.create.assert_awaited_once()
    mock_cls.get.assert_awaited_once_with("box-1", api_key=TEST_API_KEY)
    first.exec.command.assert_awaited_once_with("a")
    second.exec.command.assert_awaited_once_with("b")


async def test_sync_and_async_tools_share_a_box_when_not_persistent(run_context):
    sync_box = _sync_box("box-1")
    async_client = _async_box("box-1")
    with patch.object(box_module, "Box") as sync_cls, patch.object(box_module, "AsyncBox") as async_cls:
        sync_cls.create.return_value = sync_box
        async_cls.create = AsyncMock()
        async_cls.get = AsyncMock(return_value=async_client)
        tools = UpstashBoxTools(api_key=TEST_API_KEY, persistent=False)
        tools.create_file(run_context, "f.txt", "x")
        await tools.aread_file(run_context, "f.txt")

    async_cls.create.assert_not_awaited()
    async_cls.get.assert_awaited_once_with("box-1", api_key=TEST_API_KEY)
    assert run_context.session_state == {}


async def test_sync_shutdown_deletes_the_box_an_async_call_created(run_context):
    with patch.object(box_module, "Box") as sync_cls, patch.object(box_module, "AsyncBox") as async_cls:
        async_cls.create = AsyncMock(return_value=_async_box("box-async"))
        tools = UpstashBoxTools(api_key=TEST_API_KEY, persistent=False)
        await tools.arun_command(run_context, "ls")
        assert tools.shutdown_box(run_context) == "Box box-async shut down."

    sync_cls.create.assert_not_called()
    # No sync client is cached, so it opens one for the delete and closes it after.
    sync_cls.get.assert_called_once_with("box-async", api_key=TEST_API_KEY)
    sync_cls.get.return_value.delete.assert_called_once()
    sync_cls.get.return_value.close.assert_called_once()
    assert not tools._active_ids and not tools._async_boxes


async def test_racing_sync_and_async_creation_keeps_one_box(run_context):
    # The sync path registers its box while the async create is in flight; the async
    # path must delete its redundant box and connect to the sync one.
    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    shared = _async_box("box-sync")

    redundant = _async_box("box-async")

    async def create_while_sync_wins(**kwargs):
        tools._get_box(run_context)
        return redundant

    with patch.object(box_module, "Box") as sync_cls, patch.object(box_module, "AsyncBox") as async_cls:
        sync_cls.create.return_value = _sync_box("box-sync")
        async_cls.create = create_while_sync_wins
        async_cls.get = AsyncMock(return_value=shared)
        await tools.arun_command(run_context, "ls")

    redundant.delete.assert_awaited_once()
    redundant.aclose.assert_awaited_once()
    shared.exec.command.assert_awaited_once_with("ls")
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-sync"


def test_shutdown_of_a_box_deleted_elsewhere_succeeds_and_clears_state(run_context):
    box = _sync_box("box-gone")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        tools.run_command(run_context, "ls")
        box.delete.side_effect = _BoxError("Box has been deleted", 404)
        box.get_status.side_effect = _BoxError("Box has been deleted", 404)
        result = tools.shutdown_box(run_context)

    assert result == "Box box-gone shut down."
    mock_cls.create.assert_called_once()
    assert run_context.session_state == {}
    assert not tools._boxes and not tools._active_ids


async def test_async_shutdown_of_a_box_deleted_elsewhere_succeeds(run_context, async_box_tools):
    tools, box, _ = async_box_tools
    await tools.arun_command(run_context, "ls")
    box.delete = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    assert await tools.ashutdown_box(run_context) == "Box box-async shut down."
    assert run_context.session_state == {}
    assert not tools._async_boxes


@pytest.mark.parametrize("tool", ["pause_box", "resume_box", "snapshot_box"])
def test_lifecycle_tools_on_a_deleted_box_clear_state_without_a_replacement(run_context, tool):
    box = _sync_box("box-gone")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.create.return_value = box
        tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
        tools.run_command(run_context, "ls")
        for method in (box.pause, box.resume, box.snapshot, box.get_status):
            method.side_effect = _BoxError("Box has been deleted", 404)
        args = ("checkpoint",) if tool == "snapshot_box" else ()
        result = getattr(tools, tool)(run_context, *args)

    assert "Box box-gone no longer exists" in json.loads(result)["message"]
    mock_cls.create.assert_called_once()
    assert run_context.session_state == {}
    assert not tools._boxes


async def test_async_lifecycle_tool_on_a_deleted_box_clears_state(run_context, async_box_tools):
    tools, box, mock_cls = async_box_tools
    await tools.arun_command(run_context, "ls")
    box.pause = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    box.get_status = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    result = await tools.apause_box(run_context)
    assert "no longer exists" in json.loads(result)["message"]
    assert mock_cls.create.await_count == 1
    assert run_context.session_state == {}


# ---------------------------------------------------------------------------
# Lifecycle tools never create a box; shutdown targets the session's current box
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tool", ["pause_box", "resume_box", "snapshot_box"])
def test_lifecycle_tools_without_a_box_do_not_create_one(run_context, tool):
    with patch.object(box_module, "Box") as mock_cls:
        tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
        args = ("checkpoint",) if tool == "snapshot_box" else ()
        result = getattr(tools, tool)(run_context, *args)

    assert "No active box" in json.loads(result)["message"]
    mock_cls.create.assert_not_called()


@pytest.mark.parametrize("tool", ["pause_box", "resume_box", "snapshot_box"])
def test_lifecycle_tools_on_a_saved_deleted_box_do_not_create_one(tool):
    # A new toolkit only has the saved id; reconnecting finds the box deleted.
    run_context = RunContext(run_id="r", session_id="s", session_state={SESSION_STATE_BOX_ID: "box-deleted"})
    deleted = _sync_box("box-deleted")
    deleted.get_status.side_effect = _BoxError("Box has been deleted", 404)
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = deleted
        tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
        args = ("checkpoint",) if tool == "snapshot_box" else ()
        result = getattr(tools, tool)(run_context, *args)

    assert "Box box-deleted no longer exists" in json.loads(result)["message"]
    mock_cls.create.assert_not_called()
    assert run_context.session_state == {}
    assert not tools._active_ids


@pytest.mark.parametrize("tool", ["apause_box", "aresume_box", "asnapshot_box"])
def test_async_lifecycle_tools_on_a_saved_deleted_box_from_a_new_loop(tool):
    run_context = RunContext(run_id="r", session_id="s", session_state={SESSION_STATE_BOX_ID: "box-deleted"})
    deleted = _async_box("box-deleted")
    deleted.get_status = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.get = AsyncMock(return_value=deleted)
        mock_cls.create = AsyncMock()
        tools = UpstashBoxTools(api_key=TEST_API_KEY, all=True)
        args = ("checkpoint",) if tool == "asnapshot_box" else ()
        result = asyncio.run(getattr(tools, tool)(run_context, *args))

    assert "Box box-deleted no longer exists" in json.loads(result)["message"]
    mock_cls.create.assert_not_awaited()
    assert run_context.session_state == {}


class _GatedModel(_ScriptedModel):
    """Scripted model whose tool call waits for `start`, and which sets `done` once its
    tool has run, so two concurrent runs can be ordered deterministically."""

    def __init__(self, tool_name: str, arguments: dict, start: asyncio.Event, done: asyncio.Event) -> None:
        super().__init__(tool_name, arguments)
        self.start = start
        self.done = done

    async def ainvoke(self, *args, **kwargs):
        if self.calls == 0:
            await self.start.wait()
        else:
            self.done.set()
        return self._respond()


async def test_shutdown_from_a_run_holding_a_stale_box_id_deletes_the_current_box():
    # Two concurrent runs of one session both load box-old. Run A recovers onto
    # box-fresh after box-old is deleted elsewhere; run B then shuts down while its
    # state still says box-old. B must delete box-fresh and leave no box id saved.
    db = InMemoryDb()
    old, fresh = _async_box("box-old"), _async_box("box-fresh")
    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.create = AsyncMock(side_effect=[old, fresh])
        mock_cls.get = AsyncMock(side_effect=lambda box_id, **kwargs: {"box-old": old, "box-fresh": fresh}[box_id])
        seed = Agent(model=_ScriptedModel("run_command", {"command": "ls"}), tools=[tools], db=db, session_id="s")
        await seed.arun("create the box")
        old.exec.command = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
        old.get_status = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))

        go, recovered, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        run_a = Agent(
            model=_GatedModel("run_command", {"command": "echo hi"}, go, recovered),
            tools=[tools],
            db=db,
            session_id="s",
        )
        run_b = Agent(
            model=_GatedModel("shutdown_box", {}, recovered, finished),
            tools=[tools],
            db=db,
            session_id="s",
        )

        async def start_both():
            await asyncio.sleep(0.01)  # both runs have loaded box-old by now
            go.set()

        await asyncio.gather(run_a.arun("work"), run_b.arun("shut down"), start_both())

    fresh.delete.assert_awaited_once()
    old.delete.assert_not_awaited()
    assert not tools._active_ids and not tools._async_boxes
    saved = db.get_session(session_id="s", session_type="agent")
    assert SESSION_STATE_BOX_ID not in saved.session_data["session_state"]


def test_shutdown_box_by_id_for_an_unknown_or_deleted_box_succeeds(run_context):
    # Without a cached client the toolkit opens one; a 404 means the box is already gone.
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.side_effect = _BoxError("Box not found", 404)
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        assert tools.shutdown_box_by_id(run_context, "box-gone") == "Box box-gone shut down."
        mock_cls.delete_boxes.assert_not_called()


def test_shutdown_box_by_id_closes_the_client_it_opened(run_context):
    other = _sync_box("box-other")
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.return_value = other
        tools = UpstashBoxTools(api_key=TEST_API_KEY)
        assert tools.shutdown_box_by_id(run_context, "box-other") == "Box box-other shut down."

    other.delete.assert_called_once()
    other.close.assert_called_once()


# ---------------------------------------------------------------------------
# Concurrent shutdowns of one box shared by several sessions
# ---------------------------------------------------------------------------
async def test_concurrent_async_shutdowns_of_a_shared_box_both_succeed():
    # Two sessions share an explicit box_id, so each has its own cached client of the
    # same box. The first shutdown's cleanup suspends until the second shutdown has
    # finished; the first must neither fail nor keep its run's box id.
    second_done = asyncio.Event()
    clients = []

    def connect(*args, **kwargs):
        client = _async_box("box-shared")
        if not clients:

            async def suspended_close():
                await second_done.wait()

            client.aclose = suspended_close
        clients.append(client)
        return client

    one = RunContext(run_id="r1", session_id="one", session_state={})
    two = RunContext(run_id="r2", session_id="two", session_state={})
    with patch.object(box_module, "AsyncBox") as mock_cls:
        mock_cls.get = AsyncMock(side_effect=connect)
        tools = UpstashBoxTools(api_key=TEST_API_KEY, box_id="box-shared")
        await tools.arun_command(one, "ls")
        await tools.arun_command(two, "ls")

        async def second_shutdown():
            await asyncio.sleep(0)  # let the first shutdown reach its suspended cleanup
            result = await tools.ashutdown_box(two)
            second_done.set()
            return result

        results = await asyncio.gather(tools.ashutdown_box(one), second_shutdown())

    assert results == ["Box box-shared shut down.", "Box box-shared shut down."]
    assert one.session_state == {} and two.session_state == {}
    assert not tools._async_boxes and not tools._active_ids


def test_concurrent_sync_shutdowns_of_a_shared_box_both_succeed():
    first_closing, second_done = threading.Event(), threading.Event()
    clients = []

    def connect(*args, **kwargs):
        client = _sync_box("box-shared")
        if not clients:

            def suspended_close():
                first_closing.set()
                second_done.wait(timeout=5)

            client.close.side_effect = suspended_close
        clients.append(client)
        return client

    one = RunContext(run_id="r1", session_id="one", session_state={})
    two = RunContext(run_id="r2", session_id="two", session_state={})
    results = {}
    with patch.object(box_module, "Box") as mock_cls:
        mock_cls.get.side_effect = connect
        tools = UpstashBoxTools(api_key=TEST_API_KEY, box_id="box-shared")
        tools.run_command(one, "ls")
        tools.run_command(two, "ls")

        def shut_down(name, run_context):
            results[name] = tools.shutdown_box(run_context)

        first = threading.Thread(target=shut_down, args=("one", one))
        first.start()
        assert first_closing.wait(timeout=5)
        shut_down("two", two)
        second_done.set()
        first.join(timeout=5)

    assert results == {"one": "Box box-shared shut down.", "two": "Box box-shared shut down."}
    assert one.session_state == {} and two.session_state == {}
    assert not tools._boxes and not tools._active_ids


# ---------------------------------------------------------------------------
# A reconnect that another call superseded while it waited on the network
# ---------------------------------------------------------------------------
async def test_superseded_async_reconnect_does_not_republish_a_replaced_box():
    # The async lookup sees box-1 alive, but its status reply arrives only after box-1
    # was deleted elsewhere and the sync path replaced it with box-2. Publishing the
    # stale lookup would point the session back at box-1 and spawn a third box.
    status_seen, release = asyncio.Event(), asyncio.Event()

    sync_one, sync_two = _sync_box("box-1"), _sync_box("box-2")
    sync_two.exec.command.return_value = _run(stdout="box-2")

    stale = _async_box("box-1")

    async def delayed_alive_status():
        status_seen.set()
        await release.wait()
        return {"status": "idle"}

    stale.get_status = delayed_alive_status
    stale.exec.command = AsyncMock(side_effect=_BoxError("Box has been deleted", 404))
    current = _async_box("box-2")
    current.exec.command = AsyncMock(return_value=_run(stdout="box-2"))

    tools = UpstashBoxTools(api_key=TEST_API_KEY)
    initial, async_ctx, sync_ctx = (
        RunContext(run_id=name, session_id="shared", session_state={}) for name in ("initial", "async", "sync")
    )
    with patch.object(box_module, "Box") as sync_cls, patch.object(box_module, "AsyncBox") as async_cls:
        sync_cls.create.side_effect = [sync_one, sync_two]
        async_cls.get = AsyncMock(side_effect=lambda box_id, **kwargs: {"box-1": stale, "box-2": current}[box_id])
        async_cls.create = AsyncMock()

        tools.run_command(initial, "echo initial")  # creates box-1 through the sync path
        pending = asyncio.create_task(tools.arun_command(async_ctx, "echo async"))
        await status_seen.wait()

        # box-1 is deleted elsewhere; the sync path recovers onto box-2.
        sync_one.exec.command.side_effect = _BoxError("Box has been deleted", 404)
        sync_one.get_status.side_effect = _BoxError("Box has been deleted", 404)
        sync_result = tools.run_command(sync_ctx, "echo sync")

        release.set()
        async_result = await pending

    assert "box-2" in sync_result and "box-2" in async_result
    assert sync_cls.create.call_count == 2  # box-1 and its single replacement
    async_cls.create.assert_not_awaited()
    stale.exec.command.assert_not_awaited()  # the stale client was discarded, never used
    assert tools._active_ids == {"shared": "box-2"}
    assert sync_ctx.session_state[SESSION_STATE_BOX_ID] == "box-2"
    assert async_ctx.session_state[SESSION_STATE_BOX_ID] == "box-2"

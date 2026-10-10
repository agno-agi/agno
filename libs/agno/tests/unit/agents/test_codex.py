"""Unit tests for CodexAgent.

These exercise option mapping, session-to-thread persistence and notification
translation against a fake openai_codex module. They do not launch Codex.
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from agno.agents.codex import CodexAgent
from agno.agents.codex import agent as codex_module
from agno.db.sqlite import SqliteDb
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus

# ---------------------------------------------------------------------------
# Fake openai_codex SDK
# ---------------------------------------------------------------------------


class Sandbox(str, Enum):
    read_only = "read-only"
    workspace_write = "workspace-write"
    full_access = "full-access"


class ApprovalMode(str, Enum):
    deny_all = "deny_all"
    auto_review = "auto_review"


class ReasoningEffort(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


@dataclass
class CodexConfig:
    codex_bin: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@dataclass
class TextInput:
    text: str


@dataclass
class LocalImageInput:
    path: str


@dataclass
class ImageInput:
    url: str


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message


class FakeState:
    """Shared, scripted behaviour for the fake SDK."""

    def __init__(self) -> None:
        self.notifications: List[Any] = []
        self.unresumable: set = set()
        self.thread_counter = 0
        self.calls: List[Dict[str, Any]] = []


class FakeHandle:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def interrupt(self):
        pass

    async def stream(self):
        for notification in self._state.notifications:
            yield notification


class FakeThread:
    def __init__(self, state: FakeState, thread_id: str) -> None:
        self._state = state
        self.id = thread_id

    async def turn(self, prompt: Any, **kwargs: Any) -> FakeHandle:
        import os

        paths = [getattr(item, "path", None) for item in prompt] if isinstance(prompt, list) else []
        self._state.calls.append(
            {
                "op": "turn",
                "thread_id": self.id,
                "prompt": prompt,
                "kwargs": kwargs,
                "paths_exist": [os.path.exists(p) for p in paths if p],
            }
        )
        return FakeHandle(self._state)

    async def run(self, prompt: str, **kwargs: Any) -> Any:
        self._state.calls.append({"op": "run", "thread_id": self.id, "prompt": prompt, "kwargs": kwargs})
        return SimpleNamespace(final_response=self._state.final_response, items=[], status="completed", usage=None)

    async def compact(self) -> Any:
        self._state.calls.append({"op": "thread_compact", "thread_id": self.id})
        return SimpleNamespace()


class FakeAsyncCodex:
    state: FakeState
    # Low-level app-server client class, set by the compaction tests (AsyncCodex._client).
    client_class: Any = None

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.state.calls.append({"op": "client", "config": config})
        self._client = self.client_class(config) if self.client_class is not None else None

    async def __aenter__(self) -> "FakeAsyncCodex":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.state.calls.append({"op": "client_exit"})

    async def thread_start(self, **kwargs: Any) -> FakeThread:
        self.state.thread_counter += 1
        thread_id = f"thread-{self.state.thread_counter}"
        self.state.calls.append({"op": "thread_start", "thread_id": thread_id, "kwargs": kwargs})
        return FakeThread(self.state, thread_id)

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> FakeThread:
        if thread_id in self.state.unresumable:
            raise RuntimeError(f"no rollout found for thread id {thread_id}")
        self.state.calls.append({"op": "thread_resume", "thread_id": thread_id, "kwargs": kwargs})
        return FakeThread(self.state, thread_id)


@pytest.fixture
def fake_sdk(monkeypatch) -> FakeState:
    state = FakeState()
    FakeAsyncCodex.state = state
    module = ModuleType("openai_codex")
    module.Sandbox = Sandbox  # type: ignore[attr-defined]
    module.ApprovalMode = ApprovalMode  # type: ignore[attr-defined]
    module.CodexConfig = CodexConfig  # type: ignore[attr-defined]
    module.AsyncCodex = FakeAsyncCodex  # type: ignore[attr-defined]
    module.TextInput = TextInput  # type: ignore[attr-defined]
    module.LocalImageInput = LocalImageInput  # type: ignore[attr-defined]
    module.ImageInput = ImageInput  # type: ignore[attr-defined]

    module.JsonRpcError = JsonRpcError  # type: ignore[attr-defined]
    module.types = SimpleNamespace(ReasoningEffort=ReasoningEffort)  # type: ignore[attr-defined]
    monkeypatch.setattr(codex_module, "_sdk", lambda: module)
    return state


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield SqliteDb(db_file=path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# Notification builders (shapes mirror openai_codex app-server notifications)
# ---------------------------------------------------------------------------


def _item(**fields: Any) -> Any:
    return SimpleNamespace(root=SimpleNamespace(**fields))


def _started(item: Any) -> Any:
    return SimpleNamespace(method="item/started", payload=SimpleNamespace(item=item))


def _completed(item: Any) -> Any:
    return SimpleNamespace(method="item/completed", payload=SimpleNamespace(item=item))


def _delta(item_id: str, text: str) -> Any:
    return SimpleNamespace(method="item/agentMessage/delta", payload=SimpleNamespace(item_id=item_id, delta=text))


def _turn_completed(status: str = "completed", error: Optional[str] = None, info: Any = None) -> Any:
    turn = SimpleNamespace(
        status=SimpleNamespace(value=status),
        error=SimpleNamespace(message=error, codex_error_info=info) if error else None,
    )
    return SimpleNamespace(method="turn/completed", payload=SimpleNamespace(turn=turn))


def _collect(agent: CodexAgent, text: str, **kwargs: Any) -> List[Any]:
    async def consume():
        return [event async for event in agent._arun_stream(text, **kwargs)]

    return asyncio.run(consume())


# ---------------------------------------------------------------------------
# Option mapping
# ---------------------------------------------------------------------------


def test_thread_kwargs_map_to_sdk_options(fake_sdk):
    agent = CodexAgent(
        name="Codex",
        model="gpt-5.6-luna",
        instructions="Be terse.",
        base_instructions="You are Codex.",
        sandbox="workspace-write",
        approval_mode="deny_all",
        cwd="/repo",
        ephemeral=True,
        config={"mcp_servers": {"docs": {"url": "https://example.com/mcp"}}},
        thread_options={"service_tier": "fast", "service_name": "agno"},
    )
    sdk = codex_module._sdk()

    start = agent._thread_kwargs(sdk, resume=False)
    assert start["model"] == "gpt-5.6-luna"
    assert start["developer_instructions"] == "Be terse."
    assert start["base_instructions"] == "You are Codex."
    assert start["sandbox"] is Sandbox.workspace_write
    assert start["approval_mode"] is ApprovalMode.deny_all
    assert start["cwd"] == "/repo"
    assert start["ephemeral"] is True
    assert start["config"] == {"mcp_servers": {"docs": {"url": "https://example.com/mcp"}}}
    assert start["service_tier"] == "fast"
    assert start["service_name"] == "agno"

    resume = agent._thread_kwargs(sdk, resume=True)
    assert "ephemeral" not in resume
    assert "service_name" not in resume
    assert resume["service_tier"] == "fast"


def test_sandbox_aliases_and_validation(fake_sdk):
    sdk = codex_module._sdk()
    assert CodexAgent._to_sandbox(sdk, "read_only") is Sandbox.read_only
    assert CodexAgent._to_sandbox(sdk, "danger-full-access") is Sandbox.full_access
    with pytest.raises(ValueError, match="Unknown sandbox"):
        CodexAgent._to_sandbox(sdk, "yolo")
    with pytest.raises(ValueError, match="Unknown approval_mode"):
        CodexAgent._to_approval_mode(sdk, "ask")


def test_turn_kwargs_include_effort_and_schema(fake_sdk):
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    agent = CodexAgent(name="Codex", reasoning_effort="high", output_schema=schema, turn_options={"source": "test"})
    turn = agent._turn_kwargs(codex_module._sdk())
    assert turn["effort"] is ReasoningEffort.high
    assert turn["output_schema"] == schema
    assert turn["source"] == "test"


def test_codex_config_passes_bin_and_env(fake_sdk):
    agent = CodexAgent(name="Codex", codex_bin="/usr/local/bin/codex", env={"CODEX_API_KEY": "sk-test"})
    config = agent._codex_config(codex_module._sdk())
    assert config.codex_bin == "/usr/local/bin/codex"
    assert config.env == {"CODEX_API_KEY": "sk-test"}


# ---------------------------------------------------------------------------
# Streaming translation
# ---------------------------------------------------------------------------


def test_stream_translates_text_deltas_and_shell_commands(fake_sdk):
    fake_sdk.notifications = [
        SimpleNamespace(method="turn/started", payload=SimpleNamespace()),
        _started(_item(type="userMessage", id="u1")),
        _started(_item(type="agentMessage", id="m1", text="")),
        _delta("m1", "I'll "),
        _delta("m1", "look."),
        _completed(_item(type="agentMessage", id="m1", text="I'll look.")),
        _started(
            _item(
                type="commandExecution",
                id="c1",
                command="ls",
                cwd="/repo",
                aggregated_output=None,
                exit_code=None,
                status=SimpleNamespace(value="inProgress"),
            )
        ),
        _completed(
            _item(
                type="commandExecution",
                id="c1",
                command="ls",
                cwd="/repo",
                aggregated_output="a.py\nb.py",
                exit_code=0,
                status=SimpleNamespace(value="completed"),
            )
        ),
        _started(_item(type="agentMessage", id="m2", text="")),
        _delta("m2", "Two files."),
        _completed(_item(type="agentMessage", id="m2", text="Two files.")),
        SimpleNamespace(method="thread/tokenUsage/updated", payload=SimpleNamespace()),
        _turn_completed("completed"),
    ]
    agent = CodexAgent(name="Codex", id="codex")

    events = _collect(agent, "What is here?", session_id="s1")

    assert isinstance(events[0], RunStartedEvent)
    assert isinstance(events[-1], RunCompletedEvent)
    assert events[-1].content == "I'll look.\n\nTwo files."

    content = "".join(e.content for e in events if isinstance(e, RunContentEvent) and e.content)
    assert content == "I'll look.\n\nTwo files."

    started = [e for e in events if isinstance(e, ToolCallStartedEvent)]
    completed = [e for e in events if isinstance(e, ToolCallCompletedEvent)]
    assert len(started) == 1 and len(completed) == 1
    assert started[0].tool.tool_call_id == "c1"
    assert started[0].tool.tool_name == "shell"
    assert started[0].tool.tool_args == {"command": "ls", "cwd": "/repo"}
    assert completed[0].tool.result == "a.py\nb.py"

    turn_call = next(c for c in fake_sdk.calls if c["op"] == "turn")
    assert turn_call["prompt"] == "What is here?"


def test_stream_emits_full_message_when_no_deltas_and_pairs_mcp_without_started(fake_sdk):
    mcp_result = SimpleNamespace(content=[{"type": "text", "text": "AgentOS is a runtime."}], structured_content=None)
    fake_sdk.notifications = [
        _completed(
            _item(
                type="mcpToolCall",
                id="t1",
                server="agno_docs",
                tool="search_docs",
                arguments={"query": "AgentOS"},
                result=mcp_result,
                error=None,
                status=SimpleNamespace(value="completed"),
            )
        ),
        _completed(_item(type="agentMessage", id="m1", text="Done.")),
        _turn_completed("completed"),
    ]
    agent = CodexAgent(name="Codex", id="codex")

    events = _collect(agent, "hi")

    started = [e for e in events if isinstance(e, ToolCallStartedEvent)]
    completed = [e for e in events if isinstance(e, ToolCallCompletedEvent)]
    assert len(started) == 1 and len(completed) == 1
    assert started[0].tool.tool_name == "mcp__agno_docs__search_docs"
    assert started[0].tool.tool_args == {"query": "AgentOS"}
    assert completed[0].tool.result == "AgentOS is a runtime."
    assert events[-1].content == "Done."


def test_stream_file_change_web_search_and_failed_command_results(fake_sdk):
    kind = SimpleNamespace(root=SimpleNamespace(type="update"))
    change = SimpleNamespace(path="app.py", kind=kind, diff="-a\n+b")
    file_change = _item(type="fileChange", id="f1", changes=[change], status=SimpleNamespace(value="completed"))
    search = _item(type="webSearch", id="w1", query="agno", results=[{"title": "Agno"}])
    failed_cmd = _item(
        type="commandExecution",
        id="c2",
        command="false",
        cwd="/repo",
        aggregated_output="",
        exit_code=1,
        status=SimpleNamespace(value="failed"),
    )
    fake_sdk.notifications = [
        _started(file_change),
        _completed(file_change),
        _started(search),
        _completed(search),
        _started(failed_cmd),
        _completed(failed_cmd),
        _turn_completed("completed"),
    ]
    agent = CodexAgent(name="Codex", id="codex")

    events = _collect(agent, "edit")
    completed = {e.tool.tool_call_id: e.tool for e in events if isinstance(e, ToolCallCompletedEvent)}

    assert completed["f1"].tool_name == "apply_patch"
    assert completed["f1"].tool_args == {"changes": [{"path": "app.py", "kind": "update"}]}
    assert completed["f1"].result == "status: completed\nupdate app.py\n-a\n+b"
    assert completed["w1"].tool_name == "web_search"
    assert completed["w1"].tool_args == {"query": "agno"}
    assert '"title": "Agno"' in (completed["w1"].result or "")
    assert completed["c2"].result == "[exit code 1]"


def test_stream_reasoning_deltas_become_reasoning_content(fake_sdk):
    fake_sdk.notifications = [
        SimpleNamespace(method="item/reasoning/summaryTextDelta", payload=SimpleNamespace(delta="thinking")),
        _delta("m1", "answer"),
        _turn_completed("completed"),
    ]
    agent = CodexAgent(name="Codex", id="codex")

    events = _collect(agent, "q")
    reasoning = [e for e in events if isinstance(e, RunContentEvent) and e.reasoning_content]
    assert len(reasoning) == 1
    assert reasoning[0].reasoning_content == "thinking"
    assert reasoning[0].content == ""
    assert events[-1].content == "answer"


def test_failed_turn_surfaces_as_run_error(fake_sdk):
    fake_sdk.notifications = [
        _delta("m1", "partial"),
        _turn_completed("failed", error="model overloaded"),
    ]
    agent = CodexAgent(name="Codex", id="codex")

    events = _collect(agent, "q")
    assert isinstance(events[-1], RunErrorEvent)
    assert "model overloaded" in (events[-1].content or "")


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


def _agent_message(item_id: str, text: str, phase: Optional[str] = None) -> Any:
    return _completed(_item(type="agentMessage", id=item_id, text=text, phase=phase))


def test_non_stream_returns_final_response(fake_sdk):
    fake_sdk.notifications = [
        _agent_message("m0", "thinking out loud", phase="commentary"),
        _agent_message("m1", "pong", phase="final_answer"),
        _turn_completed(),
    ]
    agent = CodexAgent(name="Codex", id="codex", sandbox="read-only")

    out = asyncio.run(agent._arun_non_stream("ping", session_id="s1"))

    assert out.content == "pong"
    assert out.status.value == "COMPLETED" or str(out.status).endswith("completed")
    start = next(c for c in fake_sdk.calls if c["op"] == "thread_start")
    assert start["kwargs"]["sandbox"] is Sandbox.read_only


def test_final_text_falls_back_to_agent_messages():
    result = SimpleNamespace(
        final_response=None,
        items=[
            SimpleNamespace(root=SimpleNamespace(type="userMessage", text="ignored")),
            SimpleNamespace(root=SimpleNamespace(type="agentMessage", text="first")),
            SimpleNamespace(root=SimpleNamespace(type="agentMessage", text="second")),
        ],
    )
    assert CodexAgent._final_text(result) == "first\n\nsecond"


# ---------------------------------------------------------------------------
# Session <-> thread mapping
# ---------------------------------------------------------------------------


def test_thread_id_persisted_on_session_and_resumed(fake_sdk, tmp_db):
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)

    _collect(agent, "first", session_id="s1", user_id="u1")
    session = agent.read_or_create_session("s1")
    assert session.session_data["codex_thread_id"] == "thread-1"

    # A fresh agent object (simulating a restart) resumes the same thread from the DB
    agent2 = CodexAgent(name="Codex", id="codex", db=tmp_db)
    _collect(agent2, "second", session_id="s1", user_id="u1")

    ops = [c["op"] for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == ["thread_start", "thread_resume"]
    resume = next(c for c in fake_sdk.calls if c["op"] == "thread_resume")
    assert resume["thread_id"] == "thread-1"
    # Resumed threads carry their own context: prompt is sent verbatim
    second_turn = [c for c in fake_sdk.calls if c["op"] == "turn"][-1]
    assert second_turn["prompt"] == "second"


def test_unresumable_thread_starts_fresh_with_history(fake_sdk, tmp_db):
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)

    _collect(agent, "first", session_id="s1", user_id="u1")
    fake_sdk.unresumable.add("thread-1")
    _collect(agent, "second", session_id="s1", user_id="u1")

    ops = [c["op"] for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == ["thread_start", "thread_start"]
    second_turn = [c for c in fake_sdk.calls if c["op"] == "turn"][-1]
    assert "Previous conversation" in second_turn["prompt"]
    assert "user: first" in second_turn["prompt"]
    assert "assistant: ok" in second_turn["prompt"]
    assert second_turn["prompt"].endswith("Current message:\nsecond")

    session = agent.read_or_create_session("s1")
    assert session.session_data["codex_thread_id"] == "thread-2"


def test_transient_resume_failure_keeps_thread(fake_sdk, tmp_db, monkeypatch):
    """A resume that fails for any reason other than a missing thread must keep the stored id."""
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    agent.run("first", session_id="s1", user_id="u1")
    assert agent.read_or_create_session("s1").session_data["codex_thread_id"] == "thread-1"

    async def busy_resume(self, thread_id: str, **kwargs: Any) -> FakeThread:
        fake_sdk.calls.append({"op": "thread_resume", "thread_id": thread_id, "kwargs": kwargs})
        raise RuntimeError("server busy: retry limit exceeded")

    monkeypatch.setattr(FakeAsyncCodex, "thread_resume", busy_resume)
    run_output = agent.run("second", session_id="s1", user_id="u1")

    assert run_output.status == RunStatus.error
    ops = [c["op"] for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == ["thread_start", "thread_resume"], "an unrelated failure must not start a new thread"
    assert agent.read_or_create_session("s1").session_data["codex_thread_id"] == "thread-1"


def _tool_history(result: str, name: str = "shell", arguments: str = '{"command": "ls"}'):
    return [
        {"role": "user", "content": "list the files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}],
        },
        {"role": "tool", "content": result, "tool_call_id": "c1"},
        {"role": "assistant", "content": "There are many files."},
    ]


def test_history_prompt_includes_tool_calls_and_keeps_the_end_of_truncated_results():
    from agno.agents import base as base_module

    long_output = "x" * (base_module._HISTORY_TOOL_RESULT_MAX_CHARS + 500) + "\n[exit code 1]"
    prompt = CodexAgent._build_prompt("next", _tool_history(long_output), resumed=False)

    assert "user: list the files" in prompt
    assert 'assistant called shell({"command": "ls"})' in prompt
    assert "tool result: " in prompt
    assert long_output not in prompt
    assert "characters truncated" in prompt
    assert "[exit code 1]" in prompt, "the end of a tool result carries its failure status and must survive truncation"
    assert "assistant: There are many files." in prompt
    assert prompt.endswith("Current message:\nnext")
    # Resumed threads carry their own context, so history is not replayed
    assert CodexAgent._build_prompt("next", _tool_history(long_output), resumed=True) == "next"


def test_history_prompt_is_bounded_and_drops_the_oldest_entries_first():
    from agno.agents import base as base_module

    history = [{"role": "user", "content": "first question"}, {"role": "assistant", "content": "first answer"}]
    for index in range(60):
        history += _tool_history(f"output {index} " + "y" * 900)[1:3]
    history.append({"role": "user", "content": "latest question"})
    history.append({"role": "assistant", "content": "latest answer"})

    prompt = CodexAgent._build_prompt("next", history, resumed=False)

    assert len(prompt) <= base_module._HISTORY_MAX_CHARS + 500
    assert "[earlier history omitted]" in prompt
    assert "first question" not in prompt and "output 0 " not in prompt
    assert "output 59 " in prompt
    assert "user: latest question" in prompt and "assistant: latest answer" in prompt
    assert prompt.endswith("Current message:\nnext")


def test_in_memory_thread_mapping_without_db(fake_sdk):
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex")

    _collect(agent, "first", session_id="s1")
    _collect(agent, "second", session_id="s1")
    _collect(agent, "other", session_id="s2")

    ops = [(c["op"], c["thread_id"]) for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == [("thread_start", "thread-1"), ("thread_resume", "thread-1"), ("thread_start", "thread-2")]


def test_ephemeral_threads_are_not_remembered(fake_sdk, tmp_db):
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, ephemeral=True)

    _collect(agent, "first", session_id="s1", user_id="u1")
    _collect(agent, "second", session_id="s1", user_id="u1")

    ops = [c["op"] for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == ["thread_start", "thread_start"]
    session = agent.read_or_create_session("s1")
    assert "codex_thread_id" not in (session.session_data or {})
    # History is injected because the new thread has no context of its own
    second_turn = [c for c in fake_sdk.calls if c["op"] == "turn"][-1]
    assert "user: first" in second_turn["prompt"]


def test_missing_sdk_raises_helpful_import_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai_codex":
            raise ImportError("No module named 'openai_codex'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="pip install openai-codex"):
        codex_module._sdk()


@pytest.mark.asyncio
async def test_nonstream_tools_persist(fake_sdk, tmp_db):
    fake_sdk.notifications = [
        _completed(
            _item(type="commandExecution", id="call", command="pwd", aggregated_output="/workspace", exit_code=0)
        ),
        _agent_message("m1", "done"),
        _turn_completed(),
    ]
    agent = CodexAgent(db=tmp_db)
    result = await agent.arun("where", session_id="session")
    loaded = await agent.aget_run_output(result.run_id, "session")
    assert loaded.tools[0].result == "/workspace"
    assert loaded.tools[0].tool_args == {"command": "pwd"}
    assert any(m.role == "tool" and m.content == "/workspace" for m in loaded.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_interrupted_sdk_turn_is_cancelled(fake_sdk, stream):
    from agno.run.base import RunStatus

    fake_sdk.notifications = [
        SimpleNamespace(method="turn/completed", payload=SimpleNamespace(turn=SimpleNamespace(status="interrupted")))
    ]
    agent = CodexAgent()
    if stream:
        events = [e async for e in agent.arun("go", stream=True, yield_run_output=True)]
        assert any(getattr(e, "event", None) == "RunCancelled" for e in events)
        assert events[-1].status == RunStatus.cancelled
    else:
        assert (await agent.arun("go")).status == RunStatus.cancelled


@pytest.mark.parametrize("stream", [True, False])
def test_retry_resumes_the_thread_of_the_failed_attempt(fake_sdk, tmp_db, monkeypatch, stream):
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, retries=1, delay_between_retries=0)
    turns: List[int] = []
    original_stream = FakeHandle.stream

    async def stream_failing_once(self):
        turns.append(1)
        if len(turns) == 1:
            yield _turn_completed("failed", error="overloaded")
            return
        async for notification in original_stream(self):
            yield notification

    fake_sdk.notifications = [_agent_message("m1", "recovered"), _turn_completed()]
    monkeypatch.setattr(FakeHandle, "stream", stream_failing_once)
    if stream:
        events = _collect(agent, "go", session_id="s1")
        assert isinstance(events[-1], RunCompletedEvent)
        assert events[-1].content == "recovered"
    else:
        assert agent.run("go", session_id="s1").content == "recovered"

    ops = [(c["op"], c.get("thread_id")) for c in fake_sdk.calls if c["op"] in ("thread_start", "thread_resume")]
    assert ops == [("thread_start", "thread-1"), ("thread_resume", "thread-1")]
    assert [c["prompt"] for c in fake_sdk.calls if c["op"] == "turn"] == ["go", "go"]


@pytest.mark.parametrize("failure", ["failed_turn", "exception_mid_turn"])
@pytest.mark.parametrize("with_media", [False, True])
def test_non_stream_retry_keeps_the_failed_attempts_tool_calls(
    fake_sdk, tmp_db, monkeypatch, failure, tmp_path, with_media
):
    """A tool that completed in the failed attempt stays in the run, whether the turn ended with a
    failed status or died with an exception before the turn completed."""
    from agno.media import File

    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, cwd=str(tmp_path), retries=1, delay_between_retries=0)
    turns: List[int] = []
    tool_item = _item(type="commandExecution", id="call", command="pwd", aggregated_output="/workspace", exit_code=0)

    async def tool_then_failure_then_success(self):
        turns.append(1)
        if with_media:
            [attachment] = list(tmp_path.glob(".agno/uploads/*/retry.txt"))
            assert attachment.read_bytes() == b"retry payload"
        if len(turns) == 1:
            yield _completed(tool_item)
            if failure == "failed_turn":
                yield _turn_completed("failed", error="overloaded")
                return
            raise RuntimeError("connection reset mid-turn")
        yield _agent_message("m1", "recovered")
        yield _turn_completed()

    monkeypatch.setattr(FakeHandle, "stream", tool_then_failure_then_success)
    out = agent.run(
        "go", session_id="s1", files=[File(content=b"retry payload", filename="retry.txt")] if with_media else None
    )
    assert not list(tmp_path.glob(".agno/uploads/*/retry.txt"))
    assert out.status == RunStatus.completed and out.content == "recovered"
    assert len(turns) == 2
    [tool] = out.tools or []
    assert tool.tool_args == {"command": "pwd"} and tool.result == "/workspace"
    stored = agent.get_run_output(out.run_id, "s1")
    assert [m.role for m in stored.messages or []].count("tool") == 1
    assert any(m.role == "tool" and m.content == "/workspace" for m in stored.messages or [])

    if with_media:
        assert stored.input.files[0].content == b"retry payload"


def test_non_stream_exhausted_retries_keep_tools_from_every_attempt(fake_sdk, tmp_db, monkeypatch):
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, retries=1, delay_between_retries=0)
    turns: List[int] = []

    async def tool_then_exception(self):
        turns.append(1)
        yield _completed(
            _item(type="commandExecution", id=f"call-{len(turns)}", command="pwd", aggregated_output="/w", exit_code=0)
        )
        raise RuntimeError("connection reset mid-turn")

    monkeypatch.setattr(FakeHandle, "stream", tool_then_exception)
    out = agent.run("go", session_id="s1")
    assert out.status == RunStatus.error and len(turns) == 2
    assert [t.tool_call_id for t in out.tools or []] == ["call-1", "call-2"]


class CodexErrorInfoValue(str, Enum):
    usage_limit_exceeded = "usageLimitExceeded"
    server_overloaded = "serverOverloaded"
    unauthorized = "unauthorized"


@pytest.mark.parametrize(
    "info, retried",
    [
        # Shapes mirror CodexErrorInfo: a RootModel over an enum, or over a structured variant
        (SimpleNamespace(root=CodexErrorInfoValue.usage_limit_exceeded), False),
        ("sessionBudgetExceeded", False),
        ("contextWindowExceeded", False),
        ("unauthorized", False),
        (SimpleNamespace(root=CodexErrorInfoValue.server_overloaded), True),
        (SimpleNamespace(root=SimpleNamespace(http_connection_failed=SimpleNamespace(http_status_code=502))), True),
        (None, True),
    ],
    ids=["usage_limit", "session_budget", "context_window", "unauthorized", "overloaded", "connection", "none"],
)
@pytest.mark.parametrize("stream", [True, False])
def test_retry_skips_limits_and_permanent_turn_errors(fake_sdk, monkeypatch, info, retried, stream):
    agent = CodexAgent(name="Codex", id="codex", retries=2, delay_between_retries=0)
    turns: List[int] = []

    async def stream_failing(self):
        turns.append(1)
        yield _turn_completed("failed", error="turn failed", info=info)

    monkeypatch.setattr(FakeHandle, "stream", stream_failing)
    if stream:
        assert isinstance(_collect(agent, "go")[-1], RunErrorEvent)
    else:
        assert agent.run("go").status == RunStatus.error
    assert len(turns) == (3 if retried else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "info, redriven",
    [(CodexErrorInfoValue.unauthorized, False), (CodexErrorInfoValue.server_overloaded, True)],
    ids=["unauthorized", "overloaded"],
)
async def test_queue_does_not_redrive_permanent_codex_errors(fake_sdk, tmp_db, monkeypatch, info, redriven, stream):
    """The queue's own attempts stop at a failure the agent classified as permanent."""
    from ._queue_harness import run_through_queue

    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, retries=0)
    turns: List[int] = []

    async def stream_failing(self):
        turns.append(1)
        yield _turn_completed("failed", error="turn failed", info=info)

    monkeypatch.setattr(FakeHandle, "stream", stream_failing)
    job = await run_through_queue(agent, stream=stream, max_attempts=3)
    assert job["status"] == "failed"
    assert job["attempt"] == (3 if redriven else 1)
    assert len(turns) == job["attempt"]
    run = await agent.aget_run_output(job["id"], "s")
    assert run.status == RunStatus.error and run.metadata["retryable"] is redriven


@pytest.mark.parametrize("code, retried", [(-32602, False), (-32600, False), (-32001, True)])
def test_retry_skips_rejected_rpc_requests(fake_sdk, monkeypatch, code, retried):
    agent = CodexAgent(name="Codex", id="codex", retries=2, delay_between_retries=0)
    starts: List[int] = []

    async def thread_start(self, **kwargs: Any):
        starts.append(1)
        raise JsonRpcError(code, "rejected")

    monkeypatch.setattr(FakeAsyncCodex, "thread_start", thread_start)
    assert agent.run("go").status == RunStatus.error
    assert len(starts) == (3 if retried else 1)


# ---------------------------------------------------------------------------
# Configuration DX and lifecycle regressions
# ---------------------------------------------------------------------------


def test_named_settings_win_in_both_option_layers(fake_sdk):
    agent = CodexAgent(
        model="named",
        instructions="",
        sandbox="read-only",
        approval_mode="deny_all",
        cwd="/named",
        service_tier="default",
        reasoning_effort="low",
        output_schema={},
        thread_options={
            "model": "thread",
            "developer_instructions": "old",
            "sandbox": "full-access",
            "approval_mode": "auto_review",
            "cwd": "/thread",
            "service_tier": "fast",
        },
        turn_options={
            "model": "turn",
            "sandbox": "full-access",
            "approval_mode": "auto_review",
            "cwd": "/turn",
            "service_tier": "fast",
            "effort": "high",
            "output_schema": {"type": "object"},
        },
    )
    sdk = codex_module._sdk()
    for options in (agent._thread_kwargs(sdk, resume=False), agent._turn_kwargs(sdk)):
        assert options["model"] == "named"
        assert options["cwd"] == "/named"
        assert options["sandbox"] is Sandbox.read_only
        assert options["approval_mode"] is ApprovalMode.deny_all
        assert options["service_tier"] == "default"
    assert agent._thread_kwargs(sdk, resume=False)["developer_instructions"] == ""
    assert agent._turn_kwargs(sdk)["output_schema"] == {}
    assert agent._turn_kwargs(sdk)["effort"] is ReasoningEffort.low


def test_native_option_enums_and_operation_specific_keys(fake_sdk):
    agent = CodexAgent(
        thread_options={
            "sandbox": "read_only",
            "approval_mode": "deny-all",
            "ephemeral": False,
            "include_turns": True,
            "service_name": "agno",
        },
        turn_options={
            "sandbox": Sandbox.workspace_write,
            "approval_mode": ApprovalMode.deny_all,
            "effort": ReasoningEffort.low,
        },
    )
    sdk = codex_module._sdk()
    start = agent._thread_kwargs(sdk, resume=False)
    resume = agent._thread_kwargs(sdk, resume=True)
    assert start["sandbox"] is Sandbox.read_only
    assert start["approval_mode"] is ApprovalMode.deny_all
    assert "include_turns" not in start and resume["include_turns"] is True
    assert "ephemeral" not in resume and "service_name" not in resume
    assert agent._turn_kwargs(sdk)["sandbox"] is Sandbox.workspace_write
    assert agent._turn_kwargs(sdk)["effort"] is ReasoningEffort.low


@pytest.mark.parametrize("name", ["thread", "turn"])
def test_option_aliases_warn_and_conflicts_fail(fake_sdk, name):
    with pytest.warns(DeprecationWarning, match=f"{name}_options"):
        agent = CodexAgent(model="named", **{f"{name}_kwargs": {"model": "legacy"}})
    sdk = codex_module._sdk()
    resolved = agent._thread_kwargs(sdk, resume=False) if name == "thread" else agent._turn_kwargs(sdk)
    assert resolved["model"] == "named"
    with pytest.raises(ValueError, match="not both"):
        CodexAgent(**{f"{name}_options": {}, f"{name}_kwargs": {"model": "legacy"}})
    with pytest.raises(ValueError, match=f"Unknown {name} options: typo"):
        CodexAgent(**{f"{name}_options": {"typo": True}})


def test_client_and_nested_options_are_not_mutated(fake_sdk):
    native = CodexConfig(codex_bin="/original", env={"CUSTOM": "value"})
    thread = {"config": {"mcp_servers": {"old": {"url": "https://old.example"}}, "nested": [1]}}
    schema = {"properties": {"answer": {"type": "string"}}}
    agent = CodexAgent(
        client_options=native,
        codex_bin="/override",
        env={},
        thread_options=thread,
        mcp_servers={},
        turn_options={"output_schema": schema},
    )
    sdk = codex_module._sdk()
    config = agent._codex_config(sdk)
    assert config is not native and config.codex_bin == "/override" and config.env == {}
    assert native.codex_bin == "/original" and native.env == {"CUSTOM": "value"}
    inherited = CodexAgent(client_options=native)._codex_config(sdk)
    inherited.env["CUSTOM"] = "changed"
    assert native.env == {"CUSTOM": "value"}
    resolved = agent._thread_kwargs(sdk, resume=False)["config"]
    assert resolved["mcp_servers"] == {}
    resolved["nested"].append(2)
    assert thread["config"]["nested"] == [1]
    agent._turn_kwargs(sdk)["output_schema"]["properties"].clear()
    assert "answer" in schema["properties"]
    assert CodexAgent(config={}, thread_options=thread)._thread_kwargs(sdk, resume=False)["config"] == {}
    with pytest.raises(TypeError, match="CodexConfig"):
        CodexAgent(client_options={})._codex_config(sdk)


@pytest.mark.parametrize("legacy", [False, True])
def test_ephemeral_option_does_not_save_or_resume_thread(fake_sdk, tmp_db, legacy):
    options = {"thread_kwargs" if legacy else "thread_options": {"ephemeral": True}}
    if legacy:
        with pytest.warns(DeprecationWarning):
            agent = CodexAgent(db=tmp_db, **options)
    else:
        agent = CodexAgent(db=tmp_db, **options)
    for prompt in ("remember blue", "what color?"):
        assert agent.run(prompt, session_id="ephemeral").status == RunStatus.completed
    assert [c["op"] for c in fake_sdk.calls].count("thread_start") == 2
    assert not any(c["op"] == "thread_resume" for c in fake_sdk.calls)
    assert agent._thread_ids == {}
    session = tmp_db.get_session(session_id="ephemeral")
    assert "codex_thread_id" not in (session.session_data or {})
    prompts = [c["prompt"] for c in fake_sdk.calls if c["op"] == "turn"]
    assert "remember blue" in prompts[1]


def test_explicit_false_overrides_ephemeral_option(fake_sdk):
    agent = CodexAgent(ephemeral=False, thread_options={"ephemeral": True})
    agent.run("one", session_id="s")
    agent.run("two", session_id="s")
    assert any(c["op"] == "thread_resume" for c in fake_sdk.calls)
    assert next(c for c in fake_sdk.calls if c["op"] == "thread_start")["kwargs"]["ephemeral"] is False


def test_switching_to_ephemeral_clears_previous_mapping(fake_sdk, tmp_db):
    agent = CodexAgent(db=tmp_db)
    agent.run("one", session_id="s")
    agent.thread_options = {"ephemeral": True}
    agent.run("two", session_id="s")
    assert not any(c["op"] == "thread_resume" for c in fake_sdk.calls)
    assert not agent._thread_ids
    assert "codex_thread_id" not in (tmp_db.get_session(session_id="s").session_data or {})


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_native_inputs_fail_before_client_launch(fake_sdk, stream, asynchronous):
    agent = CodexAgent()
    input = [SimpleNamespace(text="hello")]
    if asynchronous:

        async def execute():
            if stream:
                return [event async for event in agent.arun(input, stream=True)]
            return await agent.arun(input)

        result = asyncio.run(execute())
    elif stream:
        result = list(agent.run(input, stream=True))
    else:
        result = agent.run(input)
    if stream:
        error = next(event for event in result if isinstance(event, RunErrorEvent))
        assert "input must be a string" in error.content
    else:
        assert result.status == RunStatus.error
        assert "input must be a string" in result.content
    assert not fake_sdk.calls


def test_mutated_invalid_options_fail_before_client_launch(fake_sdk):
    agent = CodexAgent(turn_options={})
    agent.turn_options["typo"] = True
    result = agent.run("hello")
    assert result.status == RunStatus.error and "Unknown turn options" in result.content
    assert not fake_sdk.calls


def test_typed_option_keys_match_installed_sdk():
    """Catch drift between Agno's public option keys and native SDK signatures."""
    import inspect

    sdk = pytest.importorskip("openai_codex")
    from agno.agents.codex import ThreadOptions, TurnOptions

    start = set(inspect.signature(sdk.AsyncCodex.thread_start).parameters) - {"self"}
    resume = set(inspect.signature(sdk.AsyncCodex.thread_resume).parameters) - {"self", "thread_id"}
    turn = set(inspect.signature(sdk.AsyncThread.turn).parameters) - {"self", "input"}
    assert set(ThreadOptions.__annotations__) == start | resume
    assert set(TurnOptions.__annotations__) == turn


# Compaction
# ---------------------------------------------------------------------------


def _status_changed(thread_id: str, kind: str) -> Any:
    status = SimpleNamespace(root=SimpleNamespace(type=kind))
    return SimpleNamespace(method="thread/status/changed", payload=SimpleNamespace(thread_id=thread_id, status=status))


class FakeAsyncCodexClient:
    """Low-level app-server client: only the global notification queue."""

    state: FakeState
    events: List[Any] = []
    hang: bool = False

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._events = iter(self.events)

    async def next_notification(self) -> Any:
        if self.hang:
            await asyncio.sleep(10)
        return next(self._events)


@pytest.fixture
def fake_client(fake_sdk, monkeypatch) -> type:
    FakeAsyncCodexClient.state = fake_sdk
    FakeAsyncCodexClient.events = []
    FakeAsyncCodexClient.hang = False
    monkeypatch.setattr(FakeAsyncCodex, "client_class", FakeAsyncCodexClient)
    return FakeAsyncCodexClient


def _idle_after_active(thread_id: str = "thread-1") -> List[Any]:
    return [_status_changed(thread_id, "active"), _status_changed(thread_id, "idle")]


def _started_session(fake_sdk, tmp_db, **agent_kwargs) -> CodexAgent:
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, **agent_kwargs)
    _collect(agent, "first", session_id="s1")
    return agent


def test_compact_without_a_thread_is_a_no_op(fake_client, tmp_db):
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    assert agent.compact("s1") is False
    assert not [c for c in fake_client.state.calls if c["op"] == "thread_compact"]


def test_compact_resumes_the_session_thread_and_waits_for_idle(fake_client, tmp_db):
    agent = _started_session(fake_client.state, tmp_db, model="gpt-5.6-luna", cwd="/work")
    fake_client.events = [
        _status_changed("thread-9", "active"),  # another thread, ignored
        _status_changed("thread-1", "idle"),  # idle before compaction starts, ignored
        _status_changed("thread-1", "active"),
        SimpleNamespace(method="mcpServer/startupStatus/updated", payload=SimpleNamespace()),
        _status_changed("thread-1", "idle"),
        SimpleNamespace(method="should-not-be-read", payload=SimpleNamespace()),
    ]

    assert agent.compact("s1") is True

    wanted = {"thread_resume", "thread_compact", "client_exit"}
    ops = [c["op"] for c in fake_client.state.calls if c["op"] in wanted]
    assert ops[-3:] == ["thread_resume", "thread_compact", "client_exit"]
    resume = [c for c in fake_client.state.calls if c["op"] == "thread_resume"][-1]
    assert resume["thread_id"] == "thread-1"
    assert resume["kwargs"]["model"] == "gpt-5.6-luna" and resume["kwargs"]["cwd"] == "/work"
    assert next(c for c in fake_client.state.calls if c["op"] == "thread_compact")["thread_id"] == "thread-1"


def test_compact_resumes_with_the_same_translated_options_as_a_run(fake_client, tmp_db):
    """The resume goes through the high-level client, which maps these to the wire format
    (full-access -> danger-full-access, approval_mode -> approval policy, camelCase keys).
    The low-level client would send the dict verbatim and the app-server would reject it."""
    agent = _started_session(
        fake_client.state,
        tmp_db,
        sandbox="full-access",
        instructions="Always answer in French.",
        approval_mode="deny_all",
        ephemeral=False,
    )
    fake_client.events = _idle_after_active()

    assert agent.compact("s1") is True

    [compact_resume] = [c for c in fake_client.state.calls if c["op"] == "thread_resume"]
    assert compact_resume["kwargs"]["sandbox"] is Sandbox.full_access
    assert compact_resume["kwargs"]["developer_instructions"] == "Always answer in French."
    assert compact_resume["kwargs"]["approval_mode"] is ApprovalMode.deny_all
    assert "ephemeral" not in compact_resume["kwargs"], "thread_start-only options are not sent on resume"
    # Exactly what a run's resume sends, so the SDK applies the same wire translation.
    assert compact_resume["kwargs"] == agent._thread_kwargs(codex_module._sdk(), resume=True)


def test_compact_forgets_a_thread_whose_rollout_is_gone(fake_client, tmp_db):
    agent = _started_session(fake_client.state, tmp_db)
    fake_client.state.unresumable.add("thread-1")

    assert agent.compact("s1") is False

    assert not [c for c in fake_client.state.calls if c["op"] == "thread_compact"]
    assert "codex_thread_id" not in (agent.get_session("s1").session_data or {})


def test_compact_propagates_other_resume_failures(fake_client, tmp_db, monkeypatch):
    agent = _started_session(fake_client.state, tmp_db)

    async def busy_resume(self, thread_id, **kwargs):
        raise RuntimeError("app-server busy")

    monkeypatch.setattr(FakeAsyncCodex, "thread_resume", busy_resume)
    with pytest.raises(RuntimeError, match="busy"):
        agent.compact("s1")
    assert agent.get_session("s1").session_data["codex_thread_id"] == "thread-1"


def test_compact_refuses_while_a_run_is_in_flight(fake_client, tmp_db):
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    session = AgentSession(
        session_id="s1",
        session_data={"codex_thread_id": "thread-1"},
        runs=[RunOutput(run_id="r1", status=RunStatus.running)],
    )

    async def aget_session(session_id, user_id=None):
        return session

    agent.aget_session = aget_session  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="r1 is RUNNING"):
        agent.compact("s1")
    assert not [c for c in fake_client.state.calls if c["op"] in ("thread_resume", "thread_compact")]


def test_compact_accepts_the_compacted_notification(fake_client, tmp_db):
    agent = _started_session(fake_client.state, tmp_db)
    fake_client.events = [SimpleNamespace(method="thread/compacted", payload=SimpleNamespace(thread_id="thread-1"))]
    assert asyncio.run(agent.acompact("s1")) is True


def test_compact_times_out_and_closes_the_client(fake_client, tmp_db):
    agent = _started_session(fake_client.state, tmp_db)
    fake_client.hang = True
    with pytest.raises(TimeoutError, match="did not finish compacting"):
        agent.compact("s1", timeout=0.05)
    assert [c["op"] for c in fake_client.state.calls][-1] == "client_exit"


# Metrics
# ---------------------------------------------------------------------------


def _usage(last: Dict[str, int], total: Dict[str, int]) -> Any:
    """One thread/tokenUsage/updated payload: `last` is one model request, `total` the thread so far."""
    defaults = dict(
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=0,
        cache_write_input_tokens=0,
    )
    return SimpleNamespace(
        last=SimpleNamespace(**{**defaults, **last}),
        total=SimpleNamespace(**{**defaults, **total}),
        model_context_window=258400,
    )


def _token_usage_updated(usage: Any) -> Any:
    return SimpleNamespace(method="thread/tokenUsage/updated", payload=SimpleNamespace(token_usage=usage))


def _single_request(input_tokens=14675, cached=11008, output=5, total=14680) -> Any:
    counts = dict(input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output, total_tokens=total)
    return _usage(counts, counts)


# A turn with two tool calls on a fresh thread: three model requests, each reported with
# `last` (that request) and `total` (thread so far). The turn is the whole 49434, not the
# final request's 16584.
THREE_REQUESTS = [
    _usage(
        dict(input_tokens=16300, output_tokens=46, total_tokens=16346),
        dict(input_tokens=16300, output_tokens=46, total_tokens=16346),
    ),
    _usage(
        dict(input_tokens=16450, output_tokens=54, total_tokens=16504),
        dict(input_tokens=32750, output_tokens=100, total_tokens=32850),
    ),
    _usage(
        dict(input_tokens=16520, output_tokens=64, total_tokens=16584),
        dict(input_tokens=49270, output_tokens=164, total_tokens=49434),
    ),
]


def test_non_stream_run_reports_turn_usage(fake_sdk, tmp_db):
    fake_sdk.notifications = [_token_usage_updated(_single_request()), _agent_message("m1", "pong"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, model="gpt-5.6-luna")
    out = asyncio.run(agent._arun_non_stream("ping", session_id="s1"))
    metrics = out.metrics
    assert metrics is not None
    assert (metrics.input_tokens, metrics.output_tokens, metrics.total_tokens) == (14675, 5, 14680)
    assert metrics.cache_read_tokens == 11008 and metrics.cost is None
    assert metrics.duration is not None
    [model] = metrics.details["model"]
    assert (model.id, model.provider) == ("gpt-5.6-luna", "openai")


@pytest.mark.parametrize("stream", [True, False])
def test_turn_usage_is_the_delta_of_thread_totals_not_the_last_request(fake_sdk, tmp_db, stream):
    fake_sdk.notifications = [_token_usage_updated(u) for u in THREE_REQUESTS] + [
        _agent_message("m1", "DONE"),
        _turn_completed(),
    ]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, model="gpt-5.6-luna")
    if stream:
        events = _collect(agent, "two tools", session_id="s1")
        metrics = [e for e in events if isinstance(e, RunCompletedEvent)][-1].metrics
    else:
        metrics = asyncio.run(agent._arun_non_stream("two tools", session_id="s1")).metrics
    assert metrics is not None
    assert metrics.total_tokens == 49434, "the whole turn, not the final request's 16584"
    assert (metrics.input_tokens, metrics.output_tokens) == (49270, 164)
    assert agent.get_session("s1").session_data["session_metrics"]["total_tokens"] == 49434


@pytest.mark.parametrize("stream", [True, False])
def test_turn_usage_on_a_resumed_thread_excludes_earlier_turns(fake_sdk, tmp_db, stream):
    # The thread already holds 30000 tokens from earlier turns; this turn makes two requests.
    reports = [
        _usage(
            dict(input_tokens=15000, output_tokens=10, total_tokens=15010),
            dict(input_tokens=44990, output_tokens=20, total_tokens=45010),
        ),
        _usage(
            dict(input_tokens=15100, output_tokens=12, total_tokens=15112),
            dict(input_tokens=60090, output_tokens=32, total_tokens=60122),
        ),
    ]
    fake_sdk.notifications = [_token_usage_updated(u) for u in reports] + [
        _agent_message("m1", "ok"),
        _turn_completed(),
    ]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, model="gpt-5.6-luna")
    if stream:
        metrics = [e for e in _collect(agent, "go", session_id="s1") if isinstance(e, RunCompletedEvent)][-1].metrics
    else:
        metrics = asyncio.run(agent._arun_non_stream("go", session_id="s1")).metrics
    assert metrics.total_tokens == 60122 - (45010 - 15010) == 30122
    assert (metrics.input_tokens, metrics.output_tokens) == (30100, 22)


def test_repeated_usage_report_is_not_double_counted(fake_sdk, tmp_db):
    same = THREE_REQUESTS[-1]
    fake_sdk.notifications = [_token_usage_updated(u) for u in THREE_REQUESTS + [same, same]] + [
        _agent_message("m1", "DONE"),
        _turn_completed(),
    ]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    metrics = asyncio.run(agent._arun_non_stream("go", session_id="s1")).metrics
    assert metrics.total_tokens == 49434


def test_stream_reports_usage_from_the_token_usage_notification(fake_sdk, tmp_db):
    fake_sdk.notifications = [
        _delta("m1", "pong"),
        _token_usage_updated(_single_request(output=7, total=14682)),
        _turn_completed(),
    ]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, model="gpt-5.6-luna")
    events = _collect(agent, "ping", session_id="s1")
    assert not [e for e in events if type(e).__name__ == "ExternalRunMetricsEvent"]
    completed = [e for e in events if isinstance(e, RunCompletedEvent)][-1]
    assert completed.metrics is not None and completed.metrics.output_tokens == 7
    totals = agent.get_session("s1").session_data["session_metrics"]
    assert totals["total_tokens"] == 14682


def test_session_metrics_accumulate_across_codex_runs(fake_sdk, tmp_db):
    fake_sdk.notifications = [_token_usage_updated(_single_request()), _agent_message("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, model="gpt-5.6-luna")
    asyncio.run(agent._arun_non_stream("one", session_id="s1"))
    asyncio.run(agent._arun_non_stream("two", session_id="s1"))
    totals = agent.get_session("s1").session_data["session_metrics"]
    assert totals["total_tokens"] == 2 * 14680 and totals["cache_read_tokens"] == 2 * 11008
    [model] = totals["details"]["model"]
    assert model["id"] == "gpt-5.6-luna" and model["input_tokens"] == 2 * 14675


def test_run_without_usage_reports_has_duration_only(fake_sdk, tmp_db):
    fake_sdk.notifications = [_agent_message("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    metrics = asyncio.run(agent._arun_non_stream("go", session_id="s1")).metrics
    assert metrics is not None and metrics.total_tokens == 0 and metrics.duration is not None


# ---------------------------------------------------------------------------
# Media: images as native inputs, files staged in the workspace
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(32)


@pytest.mark.parametrize("stream", [False, True])
def test_images_go_to_codex_natively_and_files_through_the_workspace(fake_sdk, tmp_db, tmp_path, stream):
    from agno.media import File, Image

    fake_sdk.notifications = [_delta("m1", "seen"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, cwd=str(tmp_path))
    media = dict(
        images=[Image(content=PNG_BYTES, format="png")],
        files=[File(content=b"a,b", filename="data.csv", mime_type="text/csv")],
    )
    if stream:
        # Through the public call, where media is validated and converted before the stream starts.
        events = list(agent.run("What is attached?", stream=True, session_id="s", **media))
        assert isinstance(events[-1], RunCompletedEvent)
        run_id = events[-1].run_id
    else:
        out = agent.run("What is attached?", session_id="s", **media)
        assert out.status == RunStatus.completed
        run_id = out.run_id

    turn = [c for c in fake_sdk.calls if c["op"] == "turn"][-1]
    items = turn["prompt"]
    assert isinstance(items, list) and isinstance(items[0], TextInput)
    assert items[0].text.startswith("What is attached?") and "data.csv" in items[0].text and "text/csv" in items[0].text
    assert "image-1.png" not in items[0].text, "images are native inputs, not prompt lines"
    [image] = [item for item in items if isinstance(item, LocalImageInput)]
    uploads = tmp_path / ".agno" / "uploads" / run_id
    assert image.path == str(uploads / "image-1.png") and turn["paths_exist"] == [True]
    assert not uploads.exists(), "attachments are removed after the run"
    stored = agent.get_run_output(run_id, "s")
    assert stored.input.files[0].filename == "data.csv" and len(stored.input.images) == 1


def test_plain_runs_still_send_a_string_prompt(fake_sdk, tmp_db):
    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    agent.run("hello", session_id="s")
    assert [c for c in fake_sdk.calls if c["op"] == "turn"][-1]["prompt"] == "hello"


def test_codex_rejects_audio(fake_sdk, tmp_db):
    from agno.exceptions import UnsupportedMediaError
    from agno.media import Audio

    agent = CodexAgent(name="Codex", id="codex", db=tmp_db)
    with pytest.raises(UnsupportedMediaError, match="audio"):
        agent.run("listen", audio=[Audio(content=b"RIFF", format="wav")])


def test_earlier_attachments_are_restaged_for_later_codex_turns(fake_sdk, tmp_db, tmp_path):
    from agno.media import File

    fake_sdk.notifications = [_delta("m1", "ok"), _turn_completed()]
    agent = CodexAgent(name="Codex", id="codex", db=tmp_db, cwd=str(tmp_path))
    first = agent.run(
        "read it", session_id="s", files=[File(content=b"a,b", filename="data.csv", mime_type="text/csv")]
    )
    expected = tmp_path / ".agno" / "uploads" / first.run_id / "data.csv"
    assert not expected.exists()

    original_turn = FakeThread.turn
    seen = {}

    async def turn(self, prompt, **kwargs):
        seen["exists"] = expected.exists()
        return await original_turn(self, prompt, **kwargs)

    FakeThread.turn = turn  # type: ignore[method-assign]
    try:
        out = agent.run("read it again", session_id="s")
    finally:
        FakeThread.turn = original_turn  # type: ignore[method-assign]
    assert out.status == RunStatus.completed and seen["exists"]
    assert [c for c in fake_sdk.calls if c["op"] == "turn"][-1]["prompt"] == "read it again"
    assert not expected.exists()

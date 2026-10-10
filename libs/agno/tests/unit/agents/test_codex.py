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


class FakeState:
    """Shared, scripted behaviour for the fake SDK."""

    def __init__(self) -> None:
        self.notifications: List[Any] = []
        self.final_response: Optional[str] = "final"
        self.unresumable: set = set()
        self.thread_counter = 0
        self.calls: List[Dict[str, Any]] = []


class FakeHandle:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def run(self):
        return SimpleNamespace(final_response=self._state.final_response, items=[], status="completed", usage=None)

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


class FakeAsyncCodex:
    state: FakeState

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.state.calls.append({"op": "client", "config": config})

    async def __aenter__(self) -> "FakeAsyncCodex":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

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


def _turn_completed(status: str = "completed", error: Optional[str] = None) -> Any:
    turn = SimpleNamespace(
        status=SimpleNamespace(value=status),
        error=SimpleNamespace(message=error) if error else None,
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


def test_non_stream_returns_final_response(fake_sdk):
    fake_sdk.final_response = "pong"
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
async def test_nonstream_tools_persist(fake_sdk, tmp_db, monkeypatch):
    async def run(self):
        return SimpleNamespace(
            final_response="done",
            items=[
                _item(type="commandExecution", id="call", command="pwd", aggregated_output="/workspace", exit_code=0)
            ],
        )

    monkeypatch.setattr(FakeHandle, "run", run)
    agent = CodexAgent(db=tmp_db)
    result = await agent.arun("where", session_id="session")
    loaded = await agent.aget_run_output(result.run_id, "session")
    assert loaded.tools[0].result == "/workspace"
    assert loaded.tools[0].tool_args == {"command": "pwd"}
    assert any(m.role == "tool" and m.content == "/workspace" for m in loaded.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_interrupted_sdk_turn_is_cancelled(fake_sdk, monkeypatch, stream):
    from agno.run.base import RunStatus

    async def run(self):
        return SimpleNamespace(status="interrupted", final_response=None, items=[])

    monkeypatch.setattr(FakeHandle, "run", run)
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

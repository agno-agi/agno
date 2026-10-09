"""Unit tests for ClaudeAgent.

These exercise SDK session persistence and resume fallback against a fake
claude_agent_sdk module. They do not launch Claude Code.
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Dict, List, Optional

import pytest

from agno.agents.claude import ClaudeAgent
from agno.agents.claude import agent as claude_module
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunErrorEvent

# ---------------------------------------------------------------------------
# Fake claude_agent_sdk
# ---------------------------------------------------------------------------


@dataclass
class ClaudeAgentOptions:
    resume: Optional[str] = None
    include_partial_messages: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any) -> None:
        self.resume = kwargs.pop("resume", None)
        self.include_partial_messages = kwargs.pop("include_partial_messages", False)
        self.extra = kwargs


@dataclass
class SystemMessage:
    subtype: str
    data: Dict[str, Any]


@dataclass
class TextBlock:
    text: str


@dataclass
class AssistantMessage:
    content: List[Any]


@dataclass
class ResultMessage:
    session_id: str
    result: str
    subtype: str = "success"
    is_error: bool = False


class StreamEvent:
    pass


class UserMessage:
    pass


class ToolUseBlock:
    pass


class ToolResultBlock:
    pass


class ProcessError(Exception):
    pass


class FakeState:
    def __init__(self) -> None:
        self.known_sessions: set = set()
        self.session_counter = 0
        self.calls: List[Dict[str, Any]] = []
        self.reply = "ok"


@pytest.fixture
def fake_sdk(monkeypatch) -> FakeState:
    state = FakeState()

    async def query(prompt: str, options: ClaudeAgentOptions):
        state.calls.append({"prompt": prompt, "resume": options.resume})
        if options.resume is not None and options.resume not in state.known_sessions:
            # Mirrors the CLI: "No conversation found" on stderr, exit 1, no messages yielded
            raise ProcessError("Command failed with exit code 1")
        if options.resume is not None:
            sdk_session_id = options.resume
        else:
            state.session_counter += 1
            sdk_session_id = f"sdk-{state.session_counter}"
            state.known_sessions.add(sdk_session_id)
        yield SystemMessage(subtype="init", data={"session_id": sdk_session_id})
        yield AssistantMessage(content=[TextBlock(text=state.reply)])
        yield ResultMessage(session_id=sdk_session_id, result=state.reply)

    module = ModuleType("claude_agent_sdk")

    class Client:
        def __init__(self, options):
            self.options = options

        async def connect(self):
            pass

        async def query(self, prompt):
            self.prompt = prompt

        def receive_response(self):
            return module.query(prompt=self.prompt, options=self.options)

        async def disconnect(self):
            pass

        async def interrupt(self):
            pass

    module.ClaudeSDKClient = Client

    for cls in (
        ClaudeAgentOptions,
        SystemMessage,
        TextBlock,
        AssistantMessage,
        ResultMessage,
        StreamEvent,
        UserMessage,
        ToolUseBlock,
        ToolResultBlock,
    ):
        setattr(module, cls.__name__, cls)
    module.query = query  # type: ignore[attr-defined]
    monkeypatch.setattr(claude_module, "_sdk", lambda: module)
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


def _collect(agent: ClaudeAgent, text: str, **kwargs: Any) -> List[Any]:
    async def consume():
        return [event async for event in agent._arun_stream(text, **kwargs)]

    return asyncio.run(consume())


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


def _run(agent: ClaudeAgent, text: str, stream: bool, **kwargs: Any) -> None:
    if stream:
        list(agent.run(text, stream=True, **kwargs))
    else:
        agent.run(text, **kwargs)


@pytest.mark.parametrize("stream", [True, False])
def test_sdk_session_persisted_and_resumed_after_restart(fake_sdk, tmp_db, stream):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    _run(agent, "first", stream, session_id="s1", user_id="u1")

    session = agent.read_or_create_session("s1")
    assert session.session_data["claude_sdk_session_id"] == "sdk-1"

    # A fresh agent object (simulating a restart) resumes the same SDK session from the DB
    agent2 = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    _run(agent2, "second", stream, session_id="s1", user_id="u1")

    assert fake_sdk.calls[-1] == {"prompt": "second", "resume": "sdk-1"}


def test_unresumable_session_starts_fresh_with_history(fake_sdk, tmp_db):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    _collect(agent, "first", session_id="s1", user_id="u1")

    # Transcript gone (other host, changed cwd): the stored id can no longer be resumed
    fake_sdk.known_sessions.clear()
    events = _collect(agent, "second", session_id="s1", user_id="u1")

    assert isinstance(events[-1], RunCompletedEvent)
    assert not any(isinstance(e, RunErrorEvent) for e in events)
    assert [c["resume"] for c in fake_sdk.calls] == [None, "sdk-1", None]
    prompt = fake_sdk.calls[-1]["prompt"]
    assert "user: first" in prompt
    assert "assistant: ok" in prompt
    assert prompt.endswith("Current message:\nsecond")

    session = agent.read_or_create_session("s1")
    assert session.session_data["claude_sdk_session_id"] == "sdk-2"


def test_in_memory_mapping_without_db(fake_sdk):
    agent = ClaudeAgent(name="Claude", id="claude")

    _collect(agent, "first", session_id="s1")
    _collect(agent, "second", session_id="s1")
    _collect(agent, "other", session_id="s2")

    assert [c["resume"] for c in fake_sdk.calls] == [None, "sdk-1", None]
    assert fake_sdk.calls[1]["prompt"] == "second"


def test_streamed_text_and_non_stream_content(fake_sdk):
    agent = ClaudeAgent(name="Claude", id="claude")
    fake_sdk.reply = "hello"

    events = _collect(agent, "hi", session_id="s1")
    assert "".join(e.content for e in events if isinstance(e, RunContentEvent)) == "hello"
    assert agent.run("hi", session_id="s2").content == "hello"


def test_failure_without_resume_is_not_retried(fake_sdk, monkeypatch):
    agent = ClaudeAgent(name="Claude", id="claude")
    calls: List[Any] = []

    async def failing_query(prompt: str, options: ClaudeAgentOptions):
        calls.append(options.resume)
        raise ProcessError("boom")
        yield  # pragma: no cover

    module = claude_module._sdk()
    monkeypatch.setattr(module, "query", failing_query)

    events = _collect(agent, "hi", session_id="s1")
    assert isinstance(events[-1], RunErrorEvent)
    assert calls == [None]


def test_store_support_and_project_key(fake_sdk, tmp_path, monkeypatch):
    from agno.agents.claude.session_store import AgnoSessionStore
    from agno.db.base import BaseDb
    from agno.db.in_memory import InMemoryDb

    agent = ClaudeAgent(id="tenant-agent", cwd="/cwd", db=SqliteDb(db_file=str(tmp_path / "db")))
    opts = agent._build_options()
    assert agent.project_key == "tenant-agent"
    assert isinstance(opts.extra["session_store"], AgnoSessionStore)
    assert opts.extra["session_store"].project_key == "tenant-agent"
    custom = ClaudeAgent(id="a", project_key="tenant", db=agent.db)
    assert custom._build_options().extra["session_store"].project_key == "tenant"
    logs = []
    monkeypatch.setattr(claude_module, "log_debug", logs.append)
    unsupported = ClaudeAgent(db=InMemoryDb())
    assert type(unsupported.db).append_transcript_entries is BaseDb.append_transcript_entries
    assert "session_store" not in unsupported._build_options().extra
    unsupported._build_options()
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_nonstream_tools_persist(fake_sdk, tmp_path, monkeypatch):
    tool = ToolUseBlock()
    tool.id, tool.name, tool.input = "call", "Read", {"path": "file"}
    result = ToolResultBlock()
    result.tool_use_id, result.content = "call", "file contents"
    user = UserMessage()
    user.content = [result]

    async def query(**kwargs):
        yield AssistantMessage([tool])
        yield user
        yield ResultMessage("sdk-id", "done")

    monkeypatch.setattr(claude_module._sdk(), "query", query)
    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")))
    run = await agent.arun("read", session_id="session")
    assert run.tools[0].result == "file contents"
    loaded = await agent.aget_run_output(run.run_id, "session")
    assert loaded.tools[0].tool_args == {"path": "file"}
    assert any(m.role == "tool" and m.content == "file contents" for m in loaded.messages)


@pytest.mark.asyncio
async def test_error_result_on_resume_falls_back_with_store(fake_sdk, tmp_path, monkeypatch):
    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")))
    await agent.arun("Remember the code bluejay", session_id="session")
    calls = []

    async def query(prompt, options):
        calls.append((prompt, options))
        if options.resume:
            yield SystemMessage("init", {"session_id": options.resume})
            yield ResultMessage(options.resume, "No conversation found", is_error=True)
        else:
            yield ResultMessage("new", "bluejay")

    monkeypatch.setattr(claude_module._sdk(), "query", query)
    run = await agent.arun("What code?", session_id="session")
    assert run.content == "bluejay"
    assert len(calls) == 2
    assert "session_store" in calls[0][1].extra
    assert "Remember the code bluejay" in calls[1][0]


@pytest.mark.asyncio
async def test_client_interrupt_and_disconnect(fake_sdk, tmp_path, monkeypatch):
    from agno.run.base import RunStatus

    sdk = claude_module._sdk()
    started, release = asyncio.Event(), asyncio.Event()
    operations = []

    class Client:
        def __init__(self, options):
            pass

        async def connect(self):
            operations.append("connect")

        async def query(self, prompt):
            operations.append("query")

        async def receive_response(self):
            started.set()
            yield AssistantMessage([TextBlock("working")])
            await release.wait()
            yield ResultMessage("sdk", "interrupted", subtype="error_during_execution", is_error=True)

        async def interrupt(self):
            operations.append("interrupt")
            release.set()

        async def disconnect(self):
            operations.append("disconnect")

    monkeypatch.setattr(sdk, "ClaudeSDKClient", Client)
    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")))
    result = asyncio.create_task(agent.arun("work", run_id="interrupt-test", session_id="s"))
    await asyncio.wait_for(started.wait(), 2)
    await agent.acancel_run("interrupt-test")
    assert (await result).status == RunStatus.cancelled
    assert operations == ["connect", "query", "interrupt", "disconnect"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_mirror_failure_is_visible_without_reexecuting(fake_sdk, tmp_db, monkeypatch, stream):
    from agno.run.agent import CustomEvent
    from agno.run.base import RunStatus

    sdk = claude_module._sdk()
    calls = []

    async def query(prompt, options):
        calls.append(prompt)
        yield SystemMessage(subtype="init", data={"session_id": "sdk-mirror"})
        yield AssistantMessage(content=[TextBlock(text="completed side effect")])
        yield SystemMessage(subtype="mirror_error", data={"error": "storage unavailable"})
        yield ResultMessage(session_id="sdk-mirror", result="completed side effect")

    monkeypatch.setattr(sdk, "query", query)
    agent = ClaudeAgent(id="mirror", db=tmp_db)
    if stream:
        events = [event async for event in agent.arun("go", session_id="s", stream=True)]
        warnings = [event for event in events if isinstance(event, CustomEvent)]
        assert len(warnings) == 1
        assert warnings[0].to_dict()["warning"]["type"] == "transcript_persistence_failed"
        result = await agent.aget_run_output(events[0].run_id, "s")
    else:
        result = await agent.arun("go", session_id="s")
    assert result.status == RunStatus.completed
    assert result.content == "completed side effect"
    assert result.metadata["warnings"][0]["error"] == "storage unavailable"
    stored = await agent.aget_run_output(result.run_id, "s")
    assert stored.metadata == result.metadata
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Continue from a message boundary
# ---------------------------------------------------------------------------


def _msg(message: Any, uuid: str) -> Any:
    message.uuid = uuid
    return message


def _user(uuid: str, content: Any) -> Any:
    user = UserMessage()
    user.content = content
    return _msg(user, uuid)


def _tool_turn(prompt: str, sdk_session_id: str = "sdk-1") -> List[Any]:
    tool = ToolUseBlock()
    tool.id, tool.name, tool.input = "call-1", "Bash", {"command": "echo alpha"}
    result = ToolResultBlock()
    result.tool_use_id, result.content = "call-1", "alpha"
    return [
        SystemMessage("init", {"session_id": sdk_session_id}),
        _user("u-prompt", prompt),
        _msg(AssistantMessage([tool]), "u-call"),
        _user("u-result", [result]),
        _msg(AssistantMessage([TextBlock("done")]), "u-final"),
        ResultMessage(sdk_session_id, "done"),
    ]


@pytest.fixture
def scripted(fake_sdk, monkeypatch):
    """Serve one scripted SDK turn per query and record prompts, resumes and forks."""
    turns: List[List[Any]] = []
    calls: List[Dict[str, Any]] = []
    forks: List[Dict[str, Any]] = []

    async def query(prompt, options):
        calls.append({"prompt": prompt, "resume": options.resume, "extra_args": options.extra.get("extra_args")})
        for message in turns.pop(0):
            yield message

    async def fork_session_via_store(store, session_id, directory=None, up_to_message_id=None):
        forks.append({"session_id": session_id, "up_to": up_to_message_id})
        return type("Fork", (), {"session_id": f"fork-{len(forks)}"})()

    module = claude_module._sdk()
    monkeypatch.setattr(module, "query", query)
    module.fork_session_via_store = fork_session_via_store
    return turns, calls, forks


def _ref(message: Any) -> Optional[Dict[str, Any]]:
    return (message.provider_data or {}).get("claude_sdk")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_runs_record_transcript_positions_and_tool_checkpoints(scripted, tmp_db, stream):
    turns, calls, _ = scripted
    turns.append(_tool_turn("go"))
    agent = ClaudeAgent(db=tmp_db)
    if stream:
        events = [event async for event in agent.arun("go", session_id="s", stream=True)]
        assert sum(type(event).__name__ == "ToolCallCompletedEvent" for event in events) == 1
        run = (await agent.aget_session("s")).runs[0]
    else:
        run = await agent.arun("go", session_id="s")
    assert calls[0]["extra_args"] == {"replay-user-messages": None}
    assert [(m.role, (_ref(m) or {}).get("uuid")) for m in run.messages] == [
        ("user", "u-prompt"),
        ("assistant", "u-call"),
        ("tool", "u-result"),
        ("assistant", "u-final"),
    ]
    assert {_ref(m)["session_id"] for m in run.messages} == {"sdk-1"}
    assert [m.checkpoint_status for m in run.messages] == [None, None, "RUNNING", None]


@pytest.mark.asyncio
async def test_fork_from_tool_result_branches_the_sdk_transcript(scripted, tmp_db):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _user("v-prompt", "next"),
            _msg(AssistantMessage([TextBlock("branched")]), "v-final"),
            ResultMessage("fork-1", "branched"),
        ]
    )
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    branch = await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from=3, fork=True, input="next")
    assert forks == [{"session_id": "sdk-1", "up_to": "u-result"}]
    assert calls[1]["resume"] == "fork-1" and calls[1]["prompt"] == "next"
    assert branch.run_id != source.run_id
    assert (branch.forked_from_run_id, branch.forked_from_message_index) == (source.run_id, 3)
    assert [m.role for m in branch.messages] == ["user", "assistant", "tool", "user", "assistant"]
    assert _ref(branch.messages[3]) == {"session_id": "fork-1", "uuid": "v-prompt"}
    assert [t.tool_call_id for t in branch.tools] == ["call-1"]
    assert len((await agent.aget_run_output(source.run_id, "s")).messages) == 4
    assert len((await agent.aget_session("s")).runs) == 2
    assert (await agent.aget_session("s")).session_data["claude_sdk_session_id"] == "fork-1"


def test_in_place_continue_keeps_run_id_and_lineage(scripted, tmp_db):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _user("v-prompt", "next"),
            _msg(AssistantMessage([TextBlock("branched")]), "v-final"),
            ResultMessage("fork-1", "branched"),
        ]
    )
    turns.append([SystemMessage("init", {"session_id": "fork-2"}), ResultMessage("fork-2", "more")])
    agent = ClaudeAgent(db=tmp_db)
    source = agent.run("go", session_id="s")
    branch = agent.continue_run(run_id=source.run_id, session_id="s", continue_from=3, fork=True, input="next")
    continued = agent.continue_run(run_id=branch.run_id, session_id="s")
    assert calls[2]["prompt"] == ClaudeAgent._CONTINUE_PROMPT
    assert forks[-1] == {"session_id": "fork-1", "up_to": "v-final"}
    assert continued.run_id == branch.run_id
    assert continued.forked_from_run_id == source.run_id
    assert continued.content == "more"
    assert len(agent.get_session("s").runs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", [None, "u-previous"])
async def test_replaying_a_turn_resends_its_prompt_from_before_it(scripted, tmp_db, parent):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(_tool_turn("go", sdk_session_id="sdk-2"))
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    tmp_db.append_transcript_entries(
        project_key=agent.project_key,
        session_id="sdk-1",
        subpath=None,
        entries=[{"type": "user", "uuid": "u-prompt", "parentUuid": parent}],
    )
    replay = await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from="last_user", fork=True)
    assert calls[1]["prompt"] == "go"
    if parent is None:
        assert forks == [] and calls[1]["resume"] is None
    else:
        assert forks == [{"session_id": "sdk-1", "up_to": "u-previous"}] and calls[1]["resume"] == "fork-1"
    assert [m.role for m in replay.messages] == ["user", "assistant", "tool", "assistant"]
    assert replay.messages[0].content == "go"
    assert replay.forked_from_message_index == 1


@pytest.mark.asyncio
async def test_continue_rejects_unrecorded_runs_and_does_not_fall_back(fake_sdk, scripted, tmp_db):
    from agno.run.base import RunStatus

    turns, calls, forks = scripted
    turns.append([SystemMessage("init", {"session_id": "sdk-1"}), ResultMessage("sdk-1", "untracked")])
    agent = ClaudeAgent(db=tmp_db)
    untracked = await agent.arun("go", session_id="s")
    with pytest.raises(ValueError, match="no Claude SDK transcript position"):
        await agent.acontinue_run(run_id=untracked.run_id, session_id="s", input="next")
    with pytest.raises(ValueError, match="regenerate"):
        agent.acontinue_run(run_id=untracked.run_id, session_id="s", regenerate=True)

    turns.append(_tool_turn("go"))
    source = await agent.arun("go", session_id="s")

    async def failing_query(prompt, options):
        calls.append({"prompt": prompt, "resume": options.resume})
        raise ProcessError("Command failed with exit code 1")
        yield  # pragma: no cover

    monkeypatch_target = claude_module._sdk()
    original = monkeypatch_target.query
    monkeypatch_target.query = failing_query
    try:
        failed = await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from=3, input="next")
    finally:
        monkeypatch_target.query = original
    assert failed.status == RunStatus.error
    assert [call["resume"] for call in calls[-1:]] == ["fork-1"]
    assert len([call for call in calls if call.get("prompt") == "next"]) == 1


@pytest.mark.asyncio
async def test_prompt_echo_does_not_block_resume_fallback(fake_sdk, tmp_path, monkeypatch):
    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")))
    await agent.arun("Remember the code bluejay", session_id="session")
    calls = []

    async def query(prompt, options):
        calls.append(options.resume)
        if options.resume:
            yield _user("echo", prompt)
            yield ResultMessage(options.resume, "No conversation found", is_error=True)
        else:
            yield ResultMessage("new", "bluejay")

    monkeypatch.setattr(claude_module._sdk(), "query", query)
    run = await agent.arun("What code?", session_id="session")
    assert run.content == "bluejay"
    assert calls == ["sdk-1", None]

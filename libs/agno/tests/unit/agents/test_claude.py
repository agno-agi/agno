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
from agno.run.base import RunStatus

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
    error: Optional[str] = None


@dataclass
class ResultMessage:
    session_id: str
    result: str
    subtype: str = "success"
    is_error: bool = False
    errors: Optional[List[str]] = None
    api_error_status: Optional[int] = None
    usage: Optional[Dict[str, Any]] = None
    total_cost_usd: Optional[float] = None
    model_usage: Optional[Dict[str, Any]] = None
    num_turns: Optional[int] = None
    duration_api_ms: Optional[int] = None


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


class ResultError(ProcessError):
    pass


class FakeState:
    def __init__(self) -> None:
        self.known_sessions: set = set()
        self.session_counter = 0
        self.calls: List[Dict[str, Any]] = []
        self.reply = "ok"
        # Extra ResultMessage fields (usage, cost, model_usage) for metrics tests
        self.result_fields: Dict[str, Any] = {}


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
        yield ResultMessage(session_id=sdk_session_id, result=state.reply, **state.result_fields)

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
        ProcessError,
        ResultError,
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


@pytest.mark.parametrize("failure", ["error_result", "result_error"])
def test_api_error_on_resume_keeps_sdk_session(fake_sdk, tmp_db, monkeypatch, failure):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    agent.run("first", session_id="s1")
    resumes = []

    async def overloaded(prompt, options):
        resumes.append(options.resume)
        if failure == "result_error":
            raise ResultError("Claude Code returned an error result: API Error: 529 Overloaded")
        yield SystemMessage("init", {"session_id": options.resume})
        yield ResultMessage(options.resume, "API Error: 529 Overloaded", subtype="success", is_error=True)

    monkeypatch.setattr(claude_module._sdk(), "query", overloaded)
    assert agent.run("second", session_id="s1").status == RunStatus.error
    assert resumes == ["sdk-1"]
    assert agent.read_or_create_session("s1").session_data["claude_sdk_session_id"] == "sdk-1"


def test_missing_session_result_error_starts_fresh(fake_sdk, tmp_db, monkeypatch):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    agent.run("first", session_id="s1")
    resumes = []

    async def missing(prompt, options):
        resumes.append(options.resume)
        if options.resume:
            raise ResultError("Claude Code returned an error result: No conversation found with session ID: sdk-1")
        yield SystemMessage("init", {"session_id": "sdk-2"})
        yield ResultMessage("sdk-2", "ok")

    monkeypatch.setattr(claude_module._sdk(), "query", missing)
    assert agent.run("second", session_id="s1").status == RunStatus.completed
    assert resumes == ["sdk-1", None]
    assert agent.read_or_create_session("s1").session_data["claude_sdk_session_id"] == "sdk-2"


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
    opts = agent._build_options(agno_session_id="agno-session")
    assert agent.project_key == "tenant-agent"
    assert isinstance(opts.extra["session_store"], AgnoSessionStore)
    assert opts.extra["session_store"].project_key == "tenant-agent"
    custom = ClaudeAgent(id="a", project_key="tenant", db=agent.db)
    assert custom._build_options(agno_session_id="agno-session").extra["session_store"].project_key == "tenant"
    logs = []
    monkeypatch.setattr(claude_module, "log_warning", logs.append)
    unsupported = ClaudeAgent(db=InMemoryDb())
    assert type(unsupported.db).append_transcript_entries is BaseDb.append_transcript_entries
    assert "session_store" not in unsupported._build_options(agno_session_id="agno-session").extra
    unsupported._build_options(agno_session_id="agno-session")
    assert len(logs) == 1, "warn once that this database keeps transcripts on local disk"
    assert "InMemoryDb" in logs[0] and "PostgresDb" in logs[0] and "SqliteDb" in logs[0]


def test_generated_project_key_warns_once(fake_sdk, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(claude_module, "log_warning", warnings.append)
    db = SqliteDb(db_file=str(tmp_path / "db"))
    for stable in (ClaudeAgent(id="a", db=db), ClaudeAgent(name="Named", db=db), ClaudeAgent(project_key="p", db=db)):
        stable._build_options(agno_session_id="agno-session")
    ClaudeAgent()._build_options(agno_session_id="agno-session")
    assert warnings == []
    generated = ClaudeAgent(db=db)
    generated._build_options(agno_session_id="agno-session")
    generated._build_options(agno_session_id="agno-session")
    assert len(warnings) == 1
    assert generated.project_key in warnings[0]


@pytest.mark.parametrize("stream", [False, True])
def test_store_records_the_runs_agno_session(fake_sdk, tmp_path, monkeypatch, stream):
    stores = []
    sdk = claude_module._sdk()
    original = sdk.query

    def query(prompt, options):
        stores.append(options.extra["session_store"])
        return original(prompt=prompt, options=options)

    monkeypatch.setattr(sdk, "query", query)
    agent = ClaudeAgent(id="a", db=SqliteDb(db_file=str(tmp_path / "db")))
    if stream:
        session_id = [e for e in agent.run("hi", stream=True)][-1].session_id
    else:
        session_id = agent.run("hi").session_id
    assert session_id and [store.agno_session_id for store in stores] == [session_id]


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


def test_user_session_store_and_file_checkpointing_disable_injection(fake_sdk, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(claude_module, "log_warning", warnings.append)
    db = SqliteDb(db_file=str(tmp_path / "db"))
    own_store = object()
    custom = ClaudeAgent(id="a", db=db, options_kwargs={"session_store": own_store})
    assert custom._build_options(agno_session_id="agno-session").extra["session_store"] is own_store

    checkpointing = ClaudeAgent(id="a", db=db, options_kwargs={"enable_file_checkpointing": True})
    opts = checkpointing._build_options(agno_session_id="agno-session")
    assert "session_store" not in opts.extra
    assert opts.extra["enable_file_checkpointing"] is True
    checkpointing._build_options(agno_session_id="agno-session")
    assert len(warnings) == 1
    assert "enable_file_checkpointing" in warnings[0]


@pytest.mark.parametrize("stream", [True, False])
def test_retry_resumes_the_sdk_session_of_the_failed_attempt(fake_sdk, tmp_db, monkeypatch, stream):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, retries=1, delay_between_retries=0)
    calls: List[Any] = []

    async def overloaded_once(prompt, options):
        calls.append({"prompt": prompt, "resume": options.resume})
        sdk_session_id = options.resume or "sdk-1"
        yield SystemMessage("init", {"session_id": sdk_session_id})
        if len(calls) == 1:
            raise ResultError("Claude Code returned an error result: API Error: 529 Overloaded")
        yield ResultMessage(sdk_session_id, "recovered")

    monkeypatch.setattr(claude_module._sdk(), "query", overloaded_once)
    if stream:
        events = _collect(agent, "go", session_id="s1")
        assert isinstance(events[-1], RunCompletedEvent)
    else:
        assert agent.run("go", session_id="s1").content == "recovered"
    assert calls == [{"prompt": "go", "resume": None}, {"prompt": "go", "resume": "sdk-1"}]


def test_non_stream_retry_keeps_the_failed_attempts_tool_calls(fake_sdk, tmp_db, monkeypatch):
    """A tool that ran in the failed attempt stays in the run; the retry resumes the session and finishes."""
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, retries=1, delay_between_retries=0)
    calls: List[Any] = []

    async def tool_then_outage(prompt, options):
        calls.append(options.resume)
        sdk_session_id = options.resume or "sdk-1"
        yield SystemMessage("init", {"session_id": sdk_session_id})
        if len(calls) == 1:
            tool = ToolUseBlock()
            tool.id, tool.name, tool.input = "call-1", "Bash", {"command": "echo alpha"}
            yield AssistantMessage([tool])
            result = ToolResultBlock()
            result.tool_use_id, result.content = "call-1", "alpha"
            user = UserMessage()
            user.content = [result]
            yield user
            raise ResultError("Claude Code returned an error result: API Error: 529 Overloaded")
        yield ResultMessage(sdk_session_id, "recovered")

    monkeypatch.setattr(claude_module._sdk(), "query", tool_then_outage)
    out = agent.run("go", session_id="s1")
    assert out.status == RunStatus.completed and out.content == "recovered"
    assert calls == [None, "sdk-1"]
    [tool] = out.tools or []
    assert (tool.tool_call_id, tool.tool_name, tool.result) == ("call-1", "Bash", "alpha")
    stored = agent.get_run_output(out.run_id, "s1")
    assert any(m.role == "tool" and m.content == "alpha" for m in stored.messages or [])


def _sdk_result_error(**fields: Any) -> ResultError:
    error = ResultError("Claude Code returned an error result")
    error.__dict__.update(fields)
    return error


@pytest.mark.parametrize(
    "failure, retried",
    [
        (ResultMessage("sdk-1", "", subtype="error_max_turns", is_error=True), False),
        (ResultMessage("sdk-1", "", subtype="error_max_budget_usd", is_error=True), False),
        (ResultMessage("sdk-1", "", subtype="error_max_structured_output_retries", is_error=True), False),
        (ResultMessage("sdk-1", "API Error: 401", is_error=True, api_error_status=401), False),
        (AssistantMessage(content=[], error="billing_error"), False),
        (_sdk_result_error(subtype="error_max_turns"), False),
        (ResultMessage("sdk-1", "API Error: 529 Overloaded", is_error=True, api_error_status=529), True),
        (ResultMessage("sdk-1", "", subtype="error_during_execution", is_error=True), True),
        (_sdk_result_error(subtype="success", api_error_status=500), True),
    ],
    ids=[
        "max_turns",
        "max_budget",
        "max_structured_output_retries",
        "status_401",
        "billing",
        "sdk_result_error_max_turns",
        "status_529",
        "during_execution",
        "sdk_result_error_500",
    ],
)
@pytest.mark.parametrize("stream", [True, False])
def test_retry_skips_limits_and_permanent_errors(fake_sdk, monkeypatch, failure, retried, stream):
    agent = ClaudeAgent(name="Claude", id="claude", retries=2, delay_between_retries=0)
    attempts: List[Any] = []

    async def failing(prompt, options):
        attempts.append(options.resume)
        yield SystemMessage("init", {"session_id": "sdk-1"})
        if isinstance(failure, Exception):
            raise failure
        yield failure
        if isinstance(failure, AssistantMessage):
            yield ResultMessage("sdk-1", "API Error: billing", is_error=True)

    monkeypatch.setattr(claude_module._sdk(), "query", failing)
    if stream:
        assert isinstance(_collect(agent, "go", session_id="s1")[-1], RunErrorEvent)
    else:
        assert agent.run("go", session_id="s1").status == RunStatus.error
    assert len(attempts) == (3 if retried else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "failure, redriven",
    [
        (ResultMessage("sdk-1", "", subtype="error_max_turns", is_error=True), False),
        (ResultMessage("sdk-1", "API Error: 401", is_error=True, api_error_status=401), False),
        (AssistantMessage(content=[], error="billing_error"), False),
        (ResultMessage("sdk-1", "API Error: 529 Overloaded", is_error=True, api_error_status=529), True),
    ],
    ids=["max_turns", "authentication", "billing", "overloaded"],
)
async def test_queue_does_not_redrive_permanent_claude_errors(fake_sdk, tmp_db, monkeypatch, failure, redriven, stream):
    """The queue's own attempts stop at a failure the agent classified as permanent."""
    from ._queue_harness import run_through_queue

    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, retries=0)
    attempts: List[Any] = []

    async def failing(prompt, options):
        attempts.append(options.resume)
        yield SystemMessage("init", {"session_id": "sdk-1"})
        yield failure
        if isinstance(failure, AssistantMessage):
            yield ResultMessage("sdk-1", "API Error: billing", is_error=True)

    monkeypatch.setattr(claude_module._sdk(), "query", failing)
    job = await run_through_queue(agent, stream=stream, max_attempts=3)
    assert job["status"] == "failed"
    assert job["attempt"] == (3 if redriven else 1)
    assert len(attempts) == job["attempt"]
    run = await agent.aget_run_output(job["id"], "s")
    assert run.status == RunStatus.error and run.metadata["retryable"] is redriven


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
            if isinstance(message, Exception):
                raise message
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
    assert _ref(branch.messages[3]) == {"session_id": "fork-1", "uuid": "v-prompt", "position": 0}
    assert [t.tool_call_id for t in branch.tools] == ["call-1"]
    assert len((await agent.aget_run_output(source.run_id, "s")).messages) == 4
    assert len((await agent.aget_session("s")).runs) == 2
    assert (await agent.aget_session("s")).session_data["claude_sdk_session_id"] == "fork-1"


def test_continuing_a_finished_run_without_fork_still_forks(scripted, tmp_db):
    """Like native agents: a completed run is never rewritten in place, whatever fork is set to."""
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
    continued = agent.continue_run(run_id=branch.run_id, session_id="s", fork=False)
    assert calls[2]["prompt"] == ClaudeAgent._CONTINUE_PROMPT
    assert forks[-1] == {"session_id": "fork-1", "up_to": "v-final"}
    assert continued.run_id != branch.run_id
    assert continued.forked_from_run_id == branch.run_id
    assert continued.forked_from_message_index == len(branch.messages)
    assert continued.content == "more"
    assert len(agent.get_session("s").runs) == 3
    assert agent.get_run_output(branch.run_id, "s").content == "branched", "the source run is untouched"


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", [None, "u-previous"])
async def test_replaying_a_turn_resends_its_prompt_from_before_it(scripted, tmp_db, parent):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(_tool_turn("go", sdk_session_id="sdk-2"))
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    tmp_db.append_transcript_entries(
        framework="claude-agent-sdk",
        project_key=agent.project_key,
        session_id="sdk-1",
        entries=[{"type": "user", "uuid": "u-prompt", "parentUuid": parent}],
        agno_session_id="s",
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


def _recorded(role: str, uuid: str, position: int, content: Any = None, **kwargs: Any) -> Any:
    from agno.models.message import Message

    return Message(
        role=role,
        content=content,
        provider_data={"claude_sdk": {"session_id": "sdk-1", "uuid": uuid, "position": position}},
        **kwargs,
    )


def _recorded_run(messages: List[Any], status: Any = None) -> Any:
    from agno.models.response import ToolExecution
    from agno.run.agent import RunInput, RunOutput
    from agno.run.base import RunStatus

    return RunOutput(
        run_id="source",
        session_id="s",
        status=status or RunStatus.completed,
        input=RunInput(input_content="go"),
        messages=messages,
        tools=[ToolExecution(tool_call_id=m.tool_call_id, tool_name="Bash") for m in messages if m.role == "tool"],
    )


def test_cancelled_runs_cannot_be_continued(fake_sdk, tmp_db):
    from agno.exceptions import RunNotContinuableError
    from agno.run.base import RunStatus

    run = _recorded_run([_recorded("user", "u-prompt", 0, "go")], status=RunStatus.cancelled)
    with pytest.raises(RunNotContinuableError, match="cancelled"):
        ClaudeAgent(db=tmp_db)._build_continuation(run, continue_from="end", fork=True, input="next")


@pytest.mark.asyncio
async def test_continue_from_zero_starts_a_branch_before_the_prompt(scripted, tmp_db):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(
        [SystemMessage("init", {"session_id": "sdk-2"}), _user("w-prompt", "fresh"), ResultMessage("sdk-2", "ok")]
    )
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    tmp_db.append_transcript_entries(
        framework="claude-agent-sdk",
        project_key=agent.project_key,
        session_id="sdk-1",
        entries=[{"type": "user", "uuid": "u-prompt", "parentUuid": None}],
        agno_session_id="s",
    )
    with pytest.raises(ValueError, match="continue_from=0"):
        await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from=0, fork=True)
    branch = await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from=0, fork=True, input="fresh")
    assert forks == [] and calls[1]["resume"] is None and calls[1]["prompt"] == "fresh"
    assert [m.role for m in branch.messages] == ["user", "assistant"] and branch.messages[0].content == "fresh"
    assert branch.forked_from_message_index == 0


def test_last_user_replays_the_selected_user_turn_not_only_the_first(fake_sdk, tmp_db):
    messages = [
        _recorded("user", "u1", 0, "first"),
        _recorded("assistant", "a1", 1, "reply one"),
        _recorded("user", "u2", 2, "second"),
        _recorded("assistant", "a2", 3, "reply two"),
    ]
    prompt, _, continuation = ClaudeAgent(db=tmp_db)._build_continuation(
        _recorded_run(messages), continue_from="last_user", fork=True, input=None
    )
    assert prompt == "second"
    assert [m.content for m in continuation.messages] == ["first", "reply one"]
    assert continuation.anchor == {"session_id": "sdk-1", "uuid": "u2", "before": True}
    assert continuation.record_input == "second"


def test_parallel_tool_batch_has_one_checkpoint_and_forks_whole(fake_sdk, tmp_db):
    # Transcript order: prompt 0, call1 1, call2 2, result2 3, result1 4, final 5; Agno lists result1 first.
    messages = [
        _recorded("user", "u", 0, "go"),
        _recorded(
            "assistant",
            "c1",
            1,
            tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}],
        ),
        _recorded("tool", "r1", 4, "alpha", tool_call_id="call-1"),
        _recorded(
            "assistant",
            "c2",
            2,
            tool_calls=[{"id": "call-2", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}],
        ),
        _recorded("tool", "r2", 3, "beta", tool_call_id="call-2"),
        _recorded("assistant", "f", 5, "done"),
    ]
    agent = ClaudeAgent(db=tmp_db)
    assert agent._checkpoint_indexes(messages) == [4], "only the end of the batch is a checkpoint"
    _, _, continuation = agent._build_continuation(_recorded_run(messages), continue_from=3, fork=True, input="next")
    assert continuation.forked_from_message_index == 5, "a boundary inside the batch moves to its end"
    assert continuation.anchor["uuid"] == "r1", "the fork keeps up to the transcript-latest result of the batch"
    assert [m.role for m in continuation.messages] == ["user", "assistant", "tool", "assistant", "tool"]
    assert sorted(t.tool_call_id for t in continuation.tools) == ["call-1", "call-2"]


@pytest.mark.asyncio
async def test_finished_run_continues_in_the_background_as_a_fork(scripted, tmp_db):
    import asyncio

    turns, _, _ = scripted
    turns.append(_tool_turn("go"))
    turns.append([SystemMessage("init", {"session_id": "fork-1"}), ResultMessage("fork-1", "more")])
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    accepted = await agent.acontinue_run(run_response=source, fork=False, background=True, input="more")
    assert accepted.run_id != source.run_id, "background continuation of a finished run must be a new run"
    for _ in range(100):
        stored = await agent.aget_run_output(accepted.run_id, "s")
        if stored is not None and getattr(stored.status, "value", stored.status) == "COMPLETED":
            break
        await asyncio.sleep(0.02)
    assert stored is not None and stored.content == "more"
    assert stored.forked_from_run_id == source.run_id
    assert (await agent.aget_run_output(source.run_id, "s")).content == "done", "the source run is untouched"


def test_sequential_tool_calls_keep_a_checkpoint_per_step(fake_sdk, tmp_db):
    # Transcript order follows Agno order: each call is issued after the previous result arrived.
    messages = [
        _recorded("user", "u", 0, "go"),
        _recorded(
            "assistant",
            "c1",
            1,
            tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}],
        ),
        _recorded("tool", "r1", 2, "alpha", tool_call_id="call-1"),
        _recorded(
            "assistant",
            "c2",
            3,
            tool_calls=[{"id": "call-2", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}],
        ),
        _recorded("tool", "r2", 4, "beta", tool_call_id="call-2"),
        _recorded("assistant", "f", 5, "done"),
    ]
    agent = ClaudeAgent(db=tmp_db)
    assert agent._checkpoint_indexes(messages) == [2, 4]
    _, _, continuation = agent._build_continuation(_recorded_run(messages), continue_from=3, fork=True, input="next")
    assert continuation.forked_from_message_index == 3 and continuation.anchor["uuid"] == "r1"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_resume_fallback_after_fork_only_replays_active_branch(scripted, tmp_db, monkeypatch, stream):
    turns, _, _ = scripted
    source_turn = _tool_turn("go")
    source_turn[-2] = _msg(AssistantMessage([TextBlock("discarded reply")]), "u-final")
    source_turn[-1] = ResultMessage("sdk-1", "discarded reply")
    turns.append(source_turn)
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _user("v-prompt", "next"),
            _msg(AssistantMessage([TextBlock("branch reply")]), "v-final"),
            ResultMessage("fork-1", "branch reply"),
        ]
    )
    agent = ClaudeAgent(id="branch-history", db=tmp_db)
    source = await agent.arun("go", session_id="s")
    await agent.acontinue_run(run_response=source, continue_from=3, input="next")
    prompts = []

    async def missing_session(prompt, options):
        prompts.append(prompt)
        if options.resume:
            raise ProcessError("No conversation found")
        yield SystemMessage("init", {"session_id": "fresh"})
        yield AssistantMessage([TextBlock("recovered")])
        yield ResultMessage("fresh", "recovered")

    monkeypatch.setattr(claude_module._sdk(), "query", missing_session)
    # A fresh adapter verifies that branch selection survives a process restart.
    restarted = ClaudeAgent(id="branch-history", db=tmp_db)
    if stream:
        events = [event async for event in restarted.arun("remember?", session_id="s", stream=True)]
        assert isinstance(events[-1], RunCompletedEvent)
    else:
        result = await restarted.arun("remember?", session_id="s")
        assert result.content == "recovered"
    assert len(prompts) == 2
    assert "discarded reply" not in prompts[-1]
    assert "branch reply" in prompts[-1]
    assert prompts[-1].count("user: go") == 1
    assert prompts[-1].count("assistant called Bash") == 1
    assert prompts[-1].count("tool result: alpha") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_agentos_automatic_fork_does_not_change_source_stream(scripted, tmp_db, monkeypatch, stream):
    from httpx import ASGITransport, AsyncClient

    import agno.os.event_streams as event_streams
    from agno.os import AgentOS
    from agno.os.event_streams import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    event_stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(event_streams, "_event_stream", event_stream)
    turns, _, _ = scripted
    turns.append(_tool_turn("go"))
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _user("v-prompt", "next"),
            ResultMessage("fork-1", "branch failed", is_error=True),
        ]
    )
    agent = ClaudeAgent(id="stream-identity", db=tmp_db)
    source = await agent.arun("go", session_id="s")
    await event_stream.register_run(source.run_id)
    await event_stream.add_event(source.run_id, RunCompletedEvent(run_id=source.run_id))
    await event_stream.complete_run(source.run_id, RunStatus.completed)
    original_events = await event_stream.replay(source.run_id)
    app = AgentOS(agents=[agent], db=tmp_db).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/agents/{agent.id}/runs/{source.run_id}/continue",
            data={"session_id": "s", "input": "next", "stream": str(stream).lower()},
        )
    assert response.status_code == 200
    branch = (await agent.aget_session("s")).runs[-1]
    assert branch.run_id != source.run_id and branch.status == RunStatus.error
    assert await event_stream.get_run_status(source.run_id) == RunStatus.completed
    assert await event_stream.replay(source.run_id) == original_events
    if stream:
        branch_events = await event_stream.replay(branch.run_id)
        assert branch_events and all(event.run_id == branch.run_id for _, event in branch_events)
        assert await event_stream.get_run_status(branch.run_id) == RunStatus.error


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["result", "exception"])
async def test_failed_run_retains_completed_tool_checkpoint(scripted, tmp_db, monkeypatch, stream, failure):
    from agno.os.checkpoints import list_run_checkpoints

    turns, _, forks = scripted
    failed_turn = _tool_turn("go")[:4]
    if failure == "result":
        turns.append(failed_turn + [ResultMessage("sdk-1", "provider failed", is_error=True)])
    else:
        original_query = claude_module._sdk().query

        async def query(prompt, options):
            if options.resume is None:
                for message in failed_turn:
                    yield message
                raise ProcessError("provider failed")
            async for message in original_query(prompt, options):
                yield message

        monkeypatch.setattr(claude_module._sdk(), "query", query)
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _user("v-prompt", ClaudeAgent._CONTINUE_PROMPT),
            _msg(AssistantMessage([TextBlock("recovered")]), "v-final"),
            ResultMessage("fork-1", "recovered"),
        ]
    )
    agent = ClaudeAgent(id="failed-checkpoint", db=tmp_db)
    if stream:
        events = [event async for event in agent.arun("go", session_id="s", stream=True)]
        assert isinstance(events[-1], RunErrorEvent)
        failed = (await agent.aget_session("s")).runs[0]
    else:
        failed = await agent.arun("go", session_id="s")
    assert failed.status == RunStatus.error and "provider failed" in failed.content
    assert [message.role for message in failed.messages] == ["user", "assistant", "tool"]
    assert failed.tools[0].result == "alpha"
    assert _ref(failed.messages[-1])["uuid"] == "u-result"
    assert failed.messages[-1].checkpoint_status == RunStatus.running.value
    assert [checkpoint["message_index"] for checkpoint in list_run_checkpoints(failed)] == [3]
    # Load from the database, so the assertion also checks serialized recovery.
    continued = await agent.acontinue_run(run_id=failed.run_id, session_id="s", fork=True)
    assert forks[-1] == {"session_id": "sdk-1", "up_to": "u-result"}
    assert continued.status == RunStatus.completed
    assert continued.tools[0].result == "alpha"
    assert [tool.tool_call_id for tool in continued.tools] == ["call-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_failed_run_retains_real_trailing_assistant_text(scripted, tmp_db, stream):
    turns, _, _ = scripted
    turns.append(_tool_turn("go")[:-1] + [ResultMessage("sdk-1", "provider failed", is_error=True)])
    agent = ClaudeAgent(id="failed-text", db=tmp_db)
    if stream:
        _ = [event async for event in agent.arun("go", session_id="s", stream=True)]
        failed = (await agent.aget_session("s")).runs[0]
    else:
        failed = await agent.arun("go", session_id="s")
    assert failed.messages[-1].content == "done"
    assert "provider failed" in failed.content
    _, _, continuation = agent._build_continuation(failed, continue_from="end", fork=True, input="next")
    assert continuation.anchor["uuid"] == "u-final"
    assert continuation.tools[0].result == "alpha"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_subagent_tools_are_not_exposed_as_checkpoints(scripted, tmp_db, stream):
    from agno.os.checkpoints import list_run_checkpoints

    turns, _, _ = scripted
    parent = _tool_turn("go")
    parent[2].content[0].id = "parent-call"
    parent[2].content[0].name = "Agent"
    parent[3].content[0].tool_use_id = "parent-call"
    child = _tool_turn("child")
    for message in child[2:4]:
        message.parent_tool_use_id = "parent-call"
    turns.append([parent[0], parent[1], parent[2], child[2], child[3], *parent[3:]])
    agent = ClaudeAgent(id="subagent-checkpoints", db=tmp_db)
    if stream:
        _ = [event async for event in agent.arun("go", session_id="s", stream=True)]
        run = (await agent.aget_session("s")).runs[0]
    else:
        run = await agent.arun("go", session_id="s")
    child_result = next(message for message in run.messages if message.tool_call_id == "call-1")
    assert child_result.checkpoint_status is None
    assert _ref(child_result) is None
    checkpoints = list_run_checkpoints(run)
    assert [checkpoint["message_index"] for checkpoint in checkpoints] == [3, 6]
    for checkpoint in checkpoints:
        _, _, continuation = agent._build_continuation(
            run, continue_from=checkpoint["message_index"], fork=True, input="next"
        )
        assert continuation.anchor["uuid"] in ("u-result", "u-final")


def test_incomplete_parallel_batch_is_not_a_checkpoint(fake_sdk, tmp_db):
    from agno.models.message import Message

    messages = [
        _recorded("user", "u", 0, "go"),
        _recorded("assistant", "c1", 1, tool_calls=[{"id": "call-1"}]),
        _recorded("tool", "r1", 3, "completed", tool_call_id="call-1"),
        _recorded("assistant", "c2", 2, tool_calls=[{"id": "call-2"}]),
        Message(role="tool", tool_call_id="call-2", content=""),
    ]
    agent = ClaudeAgent(db=tmp_db)
    assert agent._checkpoint_indexes(messages) == []
    with pytest.raises(ValueError, match="no Claude SDK transcript position"):
        agent._build_continuation(_recorded_run(messages), continue_from=3, fork=True, input="next")


def test_sync_continue_failed_run_preserves_tool_results(scripted, tmp_db):
    turns, _, forks = scripted
    turns.append(_tool_turn("go")[:4] + [ResultMessage("sdk-1", "provider failed", is_error=True)])
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            _msg(AssistantMessage([TextBlock("recovered")]), "v-final"),
            ResultMessage("fork-1", "recovered"),
        ]
    )
    agent = ClaudeAgent(id="sync-recovery", db=tmp_db)
    failed = agent.run("go", session_id="s")
    recovered = agent.continue_run(run_id=failed.run_id, session_id="s")
    assert recovered.run_id == failed.run_id
    assert recovered.status == RunStatus.completed
    assert recovered.tools[0].result == "alpha"
    assert forks == [{"session_id": "sdk-1", "up_to": "u-result"}]


@pytest.mark.asyncio
async def test_retried_continuation_forks_again_from_the_anchor(scripted, tmp_db):
    turns, calls, forks = scripted
    turns.append(_tool_turn("go"))
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-1"}),
            ResultError("Claude Code returned an error result: API Error: 529 Overloaded"),
        ]
    )
    turns.append(
        [
            SystemMessage("init", {"session_id": "fork-2"}),
            _user("v-prompt", "next"),
            _msg(AssistantMessage([TextBlock("branched")]), "v-final"),
            ResultMessage("fork-2", "branched"),
        ]
    )
    agent = ClaudeAgent(db=tmp_db)
    source = await agent.arun("go", session_id="s")
    agent.retries, agent.delay_between_retries = 1, 0
    branch = await agent.acontinue_run(run_id=source.run_id, session_id="s", continue_from=3, fork=True, input="next")

    assert branch.content == "branched"
    assert forks == [{"session_id": "sdk-1", "up_to": "u-result"}] * 2
    assert [c["resume"] for c in calls[1:]] == ["fork-1", "fork-2"]
    assert [m.role for m in branch.messages] == ["user", "assistant", "tool", "user", "assistant"]
    assert _ref(branch.messages[3]) == {"session_id": "fork-2", "uuid": "v-prompt", "position": 0}
    assert (await agent.aget_session("s")).session_data["claude_sdk_session_id"] == "fork-2"


@pytest.mark.asyncio
async def test_fork_failures_are_not_continuable_and_not_retried(fake_sdk):
    from agno.exceptions import RunNotContinuableError

    agent = ClaudeAgent(id="claude", retries=2)
    with pytest.raises(RunNotContinuableError):
        await agent._afork_sdk_session({"session_id": "sdk-1", "uuid": "u-1"}, None)
    assert agent._is_retryable_error(RunNotContinuableError("transcript entry not found")) is False


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

USAGE = {"input_tokens": 3, "output_tokens": 5, "cache_read_input_tokens": 14334, "cache_creation_input_tokens": 5369}
MODEL_USAGE = {
    "claude-sonnet-4-6": {
        "inputTokens": 3,
        "outputTokens": 5,
        "cacheReadInputTokens": 14334,
        "cacheCreationInputTokens": 5369,
        "costUSD": 0.0365982,
        "contextWindow": 200000,
    }
}


def _bill(state: FakeState) -> None:
    state.result_fields = dict(
        usage=dict(USAGE),
        total_cost_usd=0.0365982,
        model_usage={k: dict(v) for k, v in MODEL_USAGE.items()},
        num_turns=1,
        duration_api_ms=1782,
    )


def test_run_metrics_come_from_the_result_message(fake_sdk, tmp_db):
    _bill(fake_sdk)
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, model="claude-sonnet-4-6")
    run = agent.run("hi", session_id="s")
    metrics = run.metrics
    assert metrics is not None
    assert (metrics.input_tokens, metrics.output_tokens, metrics.total_tokens) == (3, 5, 8)
    assert (metrics.cache_read_tokens, metrics.cache_write_tokens) == (14334, 5369)
    assert metrics.cost == pytest.approx(0.0365982)
    assert metrics.duration is not None and metrics.duration >= 0
    assert metrics.additional_metrics == {"num_turns": 1, "api_duration": 1.782}
    [model] = metrics.details["model"]
    assert (model.id, model.provider) == ("claude-sonnet-4-6", "anthropic")
    assert model.cost == pytest.approx(0.0365982)
    stored = agent.get_run_output(run.run_id, "s")
    assert stored is not None and stored.metrics is not None and stored.metrics.total_tokens == 8


def test_streamed_runs_report_metrics_without_forwarding_the_event(fake_sdk, tmp_db):
    _bill(fake_sdk)
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, model="claude-sonnet-4-6")
    events = _collect(agent, "hi", session_id="s")
    assert not [e for e in events if type(e).__name__ == "ExternalRunMetricsEvent"]
    completed = [e for e in events if isinstance(e, RunCompletedEvent)][-1]
    assert completed.metrics is not None and completed.metrics.total_tokens == 8
    assert completed.metrics.time_to_first_token is not None


def test_session_metrics_accumulate_across_runs(fake_sdk, tmp_db):
    _bill(fake_sdk)
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, model="claude-sonnet-4-6")
    agent.run("one", session_id="s")
    agent.run("two", session_id="s")
    totals = agent.get_session("s").session_data["session_metrics"]
    assert (totals["input_tokens"], totals["output_tokens"], totals["total_tokens"]) == (6, 10, 16)
    assert totals["cache_read_tokens"] == 2 * 14334
    assert totals["cost"] == pytest.approx(2 * 0.0365982)
    assert totals["additional_metrics"]["num_turns"] == 2
    [model] = totals["details"]["model"]
    assert model["id"] == "claude-sonnet-4-6" and model["total_tokens"] == 16


def test_runs_without_usage_still_report_duration(fake_sdk, tmp_db):
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db)
    run = agent.run("hi", session_id="s")
    assert run.metrics is not None and run.metrics.total_tokens == 0 and run.metrics.duration is not None

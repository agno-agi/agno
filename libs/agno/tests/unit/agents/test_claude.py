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


class ResultError(ProcessError):
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
    with pytest.warns(DeprecationWarning, match="options_kwargs"):
        custom = ClaudeAgent(id="a", db=db, options_kwargs={"session_store": own_store})
    assert custom._build_options(agno_session_id="agno-session").extra["session_store"] is own_store

    with pytest.warns(DeprecationWarning, match="options_kwargs"):
        checkpointing = ClaudeAgent(id="a", db=db, options_kwargs={"enable_file_checkpointing": True})
    opts = checkpointing._build_options(agno_session_id="agno-session")
    assert "session_store" not in opts.extra
    assert opts.extra["enable_file_checkpointing"] is True
    checkpointing._build_options(agno_session_id="agno-session")
    assert len(warnings) == 1
    assert "enable_file_checkpointing" in warnings[0]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_typed_options_flow_through_run_and_preserve_resume(fake_sdk, monkeypatch, stream, use_async):
    @dataclass
    class NativeOptions:
        model: Optional[str] = None
        tools: Optional[List[str]] = None
        resume: Optional[str] = None
        include_partial_messages: bool = False

    sdk = claude_module._sdk()
    monkeypatch.setattr(sdk, "ClaudeAgentOptions", NativeOptions)
    captured = []
    original_query = sdk.query

    async def query(prompt, options):
        captured.append(options)
        async for message in original_query(prompt, options):
            yield message

    monkeypatch.setattr(sdk, "query", query)
    source = NativeOptions(model="base-model", tools=["Bash"])
    agent = ClaudeAgent(id="typed", options=source, model="named-model", tools=[])

    async def async_run(prompt):
        if stream:
            return [event async for event in agent.arun(prompt, session_id="session", stream=True)][-1]
        return await agent.arun(prompt, session_id="session")

    def run(prompt):
        if use_async:
            return asyncio.run(async_run(prompt))
        if stream:
            return list(agent.run(prompt, session_id="session", stream=True))[-1]
        return agent.run(prompt, session_id="session")

    first = run("first")
    second = run("second")
    if stream:
        assert isinstance(first, RunCompletedEvent) and isinstance(second, RunCompletedEvent)
    else:
        assert first.status == second.status == RunStatus.completed
    assert captured[0].resume is None
    assert captured[1].resume == "sdk-1"
    assert all(item.model == "named-model" and item.tools == [] for item in captured)
    assert all(item.include_partial_messages == stream for item in captured)
    assert source.model == "base-model" and source.tools == ["Bash"] and source.resume is None


# ---------------------------------------------------------------------------
# Media: attachments staged in the workspace
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(32)


def _attachment_paths(prompt: str) -> List[str]:
    return [line[2:].split(" (")[0] for line in prompt.splitlines() if line.startswith("- ")]


@pytest.mark.parametrize("stream", [False, True])
def test_images_and_files_are_staged_and_named_in_the_prompt(fake_sdk, tmp_db, tmp_path, monkeypatch, stream):
    import os

    from agno.media import File, Image

    seen: Dict[str, Any] = {}

    async def query(prompt, options):
        paths = _attachment_paths(prompt)
        seen.update(prompt=prompt, paths=paths, exists=[os.path.exists(p) for p in paths])
        yield SystemMessage("init", {"session_id": "sdk-1"})
        yield ResultMessage("sdk-1", "seen")

    monkeypatch.setattr(claude_module._sdk(), "query", query)
    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, cwd=str(tmp_path))
    media = dict(
        images=[Image(content=PNG_BYTES, format="png")],
        files=[File(content=b"hello", filename="notes.txt", mime_type="text/plain")],
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

    assert seen["prompt"].startswith("What is attached?") and "Attached files" in seen["prompt"]
    assert len(seen["paths"]) == 2 and seen["exists"] == [True, True]
    uploads = tmp_path / ".agno" / "uploads"
    assert all(p.startswith(str(uploads / run_id)) for p in seen["paths"])
    assert seen["paths"][0].endswith("image-1.png") and seen["paths"][1].endswith("notes.txt")
    assert "image/png" in seen["prompt"] and "text/plain" in seen["prompt"]
    assert not (uploads / run_id).exists(), "attachments are removed after the run"
    stored = agent.get_run_output(run_id, "s")
    assert stored.input.files[0].filename == "notes.txt" and len(stored.input.images) == 1


def test_keep_uploads_leaves_attachments_in_the_workspace(fake_sdk, tmp_db, tmp_path):
    from agno.media import File

    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, cwd=str(tmp_path), keep_uploads=True)
    out = agent.run("read it", session_id="s", files=[File(content=b"x", filename="a.txt", mime_type="text/plain")])
    kept = list((tmp_path / ".agno" / "uploads" / out.run_id).iterdir())
    assert [p.name for p in kept] == ["a.txt"]


def test_audio_and_video_are_still_rejected(fake_sdk, tmp_db, tmp_path):
    from agno.exceptions import UnsupportedMediaError
    from agno.media import Audio

    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, cwd=str(tmp_path))
    with pytest.raises(UnsupportedMediaError, match="audio"):
        agent.run("listen", audio=[Audio(content=b"RIFF", format="wav")])
    assert not [c for c in fake_sdk.calls]


def test_earlier_attachments_are_restaged_for_later_turns(fake_sdk, tmp_db, tmp_path, monkeypatch):
    """A later turn, possibly on another replica, finds the files an earlier run was given,
    at the paths the transcript already names, and they are removed again afterwards."""
    import os

    from agno.media import File

    agent = ClaudeAgent(name="Claude", id="claude", db=tmp_db, cwd=str(tmp_path))
    first = agent.run(
        "read it", session_id="s", files=[File(content=b"v1", filename="spec.txt", mime_type="text/plain")]
    )
    expected = tmp_path / ".agno" / "uploads" / first.run_id / "spec.txt"
    assert not expected.exists()

    seen: Dict[str, Any] = {}

    async def query(prompt, options):
        seen.update(
            prompt=prompt, exists=os.path.exists(expected), content=expected.read_bytes() if expected.exists() else None
        )
        yield SystemMessage("init", {"session_id": options.resume or "sdk-1"})
        yield ResultMessage(options.resume or "sdk-1", "again")

    monkeypatch.setattr(claude_module._sdk(), "query", query)
    # A fresh agent object with a different working directory stands in for another replica.
    other = ClaudeAgent(name="Claude", id="claude", db=tmp_db, cwd=str(tmp_path))
    out = other.run("read it again", session_id="s")
    assert out.status == RunStatus.completed
    assert seen["exists"] and seen["content"] == b"v1"
    assert "Attached files" not in seen["prompt"], "earlier attachments are not announced again"
    assert not expected.exists(), "re-staged files are removed after the turn"

"""Prime Agent event translation and session persistence without invoking the CLI."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agno.agents.prime import PrimeAgent
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
from agno.session.agent import AgentSession


class StubProcess:
    def __init__(self, events, *, returncode=0, stderr=b""):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        for event in events:
            self.stdout.feed_data(json.dumps(event).encode() + b"\n")
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.returncode = returncode

    async def wait(self):
        return self.returncode


def answer_events(text="Hello", native_id="prime-1", *, deltas=False):
    events = [
        {"type": "session", "id": native_id},
        {"type": "agent_start"},
        {"type": "message_start", "message": {"role": "assistant"}},
    ]
    if deltas:
        events.append(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": text},
            }
        )
    events.extend(
        [
            {
                "type": "message_end",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "stopReason": "stop"},
            },
            {"type": "agent_end", "messages": []},
        ]
    )
    return events


@pytest.mark.asyncio
async def test_stream_text_and_tools_without_duplicate_text():
    events = answer_events(deltas=True)
    events[1:1] = [
        {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "ipython", "args": {"code": "2+2"}},
        {
            "type": "tool_execution_end",
            "toolCallId": "call-1",
            "toolName": "ipython",
            "result": {"content": [{"type": "text", "text": "4"}], "isError": False},
        },
    ]
    agent = PrimeAgent(name="Prime")
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=StubProcess(events))):
        result = [event async for event in agent.arun("hello", stream=True)]
    assert isinstance(result[0], RunStartedEvent)
    assert isinstance(result[-1], RunCompletedEvent)
    assert "".join(event.content for event in result if isinstance(event, RunContentEvent)) == "Hello"
    started = next(event for event in result if isinstance(event, ToolCallStartedEvent))
    completed = next(event for event in result if isinstance(event, ToolCallCompletedEvent))
    assert started.tool.tool_args == {"code": "2+2"}
    assert completed.tool.tool_call_id == started.tool.tool_call_id
    assert completed.tool.result == "4"


@pytest.mark.asyncio
async def test_resume_survives_adapter_recreation(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "prime.db"))
    agent = PrimeAgent(id="prime", db=db)
    with patch(
        "agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=StubProcess(answer_events()))
    ):
        first = await agent.arun("hello", session_id="s1", user_id="u1")
    assert first.status == RunStatus.completed
    recreated = PrimeAgent(id="prime", db=db)
    spawn = AsyncMock(return_value=StubProcess(answer_events("Again")))
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        second = await recreated.arun("again", session_id="s1", user_id="u1")
    command = spawn.call_args.args
    assert command[command.index("--resume") + 1] == "prime-1"
    assert command[-1] == "again"
    assert second.content == "Again"
    assert len(db.get_runs(session_id="s1")) == 2


@pytest.mark.asyncio
async def test_native_sessions_are_scoped_by_user_and_session():
    agent = PrimeAgent(name="Prime")
    spawn = AsyncMock(side_effect=[StubProcess(answer_events(native_id=f"prime-{index}")) for index in range(4)])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        await agent.arun("first", session_id="s1", user_id="u1")
        await agent.arun("other user", session_id="s1", user_id="u2")
        await agent.arun("other session", session_id="s2", user_id="u1")
        await agent.arun("again", session_id="s1", user_id="u1")
    assert all("--resume" not in call.args for call in spawn.call_args_list[:3])
    command = spawn.call_args_list[3].args
    assert command[command.index("--resume") + 1] == "prime-0"


def test_sync_run_and_literal_prompt():
    async def spawn(*args, **kwargs):
        assert args[-3:] == ("--print", "--", "@file --resume other")
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        return StubProcess(answer_events())

    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        result = PrimeAgent(name="Prime").run("@file --resume other")
    assert result.content == "Hello"
    assert result.status == RunStatus.completed


@pytest.mark.asyncio
async def test_nonzero_exit_surfaces_run_error():
    process = StubProcess(answer_events(), returncode=1, stderr=b"invalid model")
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        events = [event async for event in PrimeAgent().arun("hello", stream=True)]
    assert isinstance(events[-1], RunErrorEvent)
    assert "invalid model" in events[-1].content
    assert not any(isinstance(event, RunCompletedEvent) for event in events)


@pytest.mark.asyncio
async def test_missing_terminal_event_is_an_error():
    process = StubProcess(answer_events()[:-1])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await PrimeAgent().arun("hello")
    assert result.status == RunStatus.error
    assert "agent_end" in result.content


@pytest.mark.asyncio
async def test_missing_executable_is_actionable():
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError())):
        result = await PrimeAgent().arun("hello")
    assert result.status == RunStatus.error
    assert "Install prime-agent" in result.content


@pytest.mark.asyncio
async def test_message_streaming_state_resets_between_assistant_messages():
    events = answer_events("First", deltas=True)[:-1]
    events.extend(answer_events("Second")[2:])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=StubProcess(events))):
        result = await PrimeAgent().arun("hello")
    assert result.content == "FirstSecond"


@pytest.mark.asyncio
async def test_persisted_session_cannot_be_resumed_by_another_user():
    agent = PrimeAgent()
    session = AgentSession(session_id="s1", user_id="u1", session_data={agent._SESSION_KEY: "prime-private"})
    spawn = AsyncMock()
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        with pytest.raises(ValueError, match="different user"):
            await agent._arun_adapter("hello", session=session, user_id="u2")
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_terminates_and_reaps_process():
    process = StubProcess([])
    process.stdout = asyncio.StreamReader()  # An open pipe that never produces output.
    process.returncode = None
    process.pid = 12345

    async def communicate():
        process.returncode = -15
        return b"", b""

    process.communicate = AsyncMock(side_effect=communicate)
    process.terminate = lambda: None
    with (
        patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
        patch("agno.agents.prime.agent.os.killpg", create=True) as killpg,
    ):
        result = await PrimeAgent(timeout=0.01).arun("hello")
    assert result.status == RunStatus.error
    assert "exceeded" in result.content
    process.communicate.assert_awaited_once()
    if os.name == "posix":
        killpg.assert_called_once()


def test_keyword_configuration_and_read_only_sdk():
    agent = PrimeAgent(name="Prime")
    assert agent.sdk == agent.framework == "prime-agent"
    with pytest.raises(TypeError):
        PrimeAgent("Prime")
    with pytest.raises(TypeError):
        PrimeAgent(framework="other")
    with pytest.raises(AttributeError):
        agent.sdk = "other"
    with pytest.raises(ValueError, match="output_schema"):
        PrimeAgent(output_schema={"type": "object", "properties": {}})
    with pytest.raises(ValueError, match="thinking"):
        PrimeAgent(thinking="unsupported")
    with pytest.raises(ValueError, match="positive"):
        PrimeAgent(timeout=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_tools_and_metrics_are_retained_in_both_run_modes(stream):
    events = answer_events()
    events[3]["message"].update(
        model="prime-default",
        provider="anthropic",
        usage={
            "input": 10,
            "output": 3,
            "cacheRead": 20,
            "cacheWrite": 5,
            "totalTokens": 38,
            "cost": {"total": 0.1},
        },
    )
    events[1:1] = [
        {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "python_repl", "args": {"code": "2+2"}},
        {
            "type": "tool_execution_end",
            "toolCallId": "call-1",
            "toolName": "python_repl",
            "result": {"content": [{"type": "text", "text": "4"}]},
        },
    ]
    agent = PrimeAgent()
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=StubProcess(events))):
        if stream:
            result = [event async for event in agent.arun("hello", stream=True, yield_run_output=True)][-1]
        else:
            result = await agent.arun("hello")
    assert result.content == "Hello"
    assert result.model == "prime-default"
    assert result.model_provider == "anthropic"
    assert result.tools[0].result == "4"
    assert result.tools[0].tool_args == {"code": "2+2"}
    assert result.metrics.input_tokens == 10
    assert result.metrics.output_tokens == 3
    assert result.metrics.total_tokens == 38
    assert result.metrics.cache_read_tokens == 20
    assert result.metrics.cache_write_tokens == 5
    assert result.metrics.cost == pytest.approx(0.1)
    assert result.metrics.details["model"][0].id == "prime-default"
    assert result.metrics.duration is not None


@pytest.mark.asyncio
async def test_metrics_sum_model_requests_once_and_persist_session_totals(tmp_path):
    events = answer_events("First")[:-1] + answer_events("Second")[2:]
    for event in events:
        message = event.get("message", {})
        if event["type"] == "message_end":
            message.update(model="m1", provider="openai", usage={"input": 7, "output": 2, "cost": {"total": 0.05}})
    # The terminal messages repeat the same messages; they must not count twice.
    events[-1]["messages"] = [event["message"] for event in events if event["type"] == "message_end"]
    db = SqliteDb(db_file=str(tmp_path / "metrics.db"))
    agent = PrimeAgent(id="prime-metrics", db=db)
    spawn = AsyncMock(side_effect=[StubProcess(events), StubProcess(events)])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        first = await agent.arun("hello", session_id="s1")
        await agent.arun("again", session_id="s1")
    assert first.metrics.total_tokens == 18
    assert first.metrics.cost == pytest.approx(0.1)
    assert len(first.metrics.details["model"]) == 1
    assert first.metrics.details["model"][0].input_tokens == 14
    totals = agent.get_session("s1").session_data["session_metrics"]
    assert totals["total_tokens"] == 36
    assert totals["cost"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_tool_result_message_reports_error_without_mutating_started_event():
    events = answer_events()
    events[1:1] = [
        {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "python_repl", "args": {"code": "bad"}},
        {
            "type": "tool_execution_end",
            "toolCallId": "call-1",
            "toolName": "python_repl",
            "result": {"content": [{"type": "text", "text": "failed"}]},
        },
        {"type": "message_end", "message": {"role": "toolResult", "toolCallId": "call-1", "isError": True}},
    ]
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=StubProcess(events))):
        result = [event async for event in PrimeAgent().arun("hello", stream=True, yield_run_output=True)]
    started = next(event for event in result if isinstance(event, ToolCallStartedEvent))
    assert started.tool.result is None
    assert result[-1].tools[0].tool_call_error is True
    assert result[-1].tools[0].result == "failed"


@pytest.mark.asyncio
async def test_ephemeral_runs_do_not_resume_or_save_native_id(tmp_path):
    agent = PrimeAgent(id="prime", ephemeral=True, db=SqliteDb(db_file=str(tmp_path / "ephemeral.db")))
    spawn = AsyncMock(side_effect=[StubProcess(answer_events()), StubProcess(answer_events())])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        await agent.arun("first", session_id="s1")
        await agent.arun("second", session_id="s1")
    assert all("--no-session" in call.args and "--resume" not in call.args for call in spawn.call_args_list)
    assert not agent._session_ids
    session = agent.get_session("s1")
    assert agent._SESSION_KEY not in session.session_data
    assert "first" in spawn.call_args_list[1].args[-1]
    assert await agent.acompact("s1") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_uploads", [False, True])
async def test_native_attachments_and_cleanup(tmp_path, keep_uploads):
    from agno.media import File, Image

    image = Image(content=b"image bytes", format="png")
    file = File(content=b"project notes", filename="notes.txt")
    staged_paths = []

    async def spawn(*args, **kwargs):
        assert args[-1] == "@literal-prompt"
        delimiter = args.index("--")
        staged_paths.extend(Path(arg[1:]) for arg in args[:delimiter] if arg.startswith("@"))
        assert len(staged_paths) == 2
        assert all(path.exists() for path in staged_paths)
        assert {path.read_bytes() for path in staged_paths} == {b"image bytes", b"project notes"}
        return StubProcess(answer_events())

    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        result = await PrimeAgent(cwd=str(tmp_path), keep_uploads=keep_uploads).arun(
            "@literal-prompt", images=[image], files=[file]
        )
    assert result.status == RunStatus.completed
    assert all(path.exists() == keep_uploads for path in staged_paths)
    assert result.input.images == [image]
    assert result.input.files == [file]


@pytest.mark.asyncio
async def test_unsupported_input_and_media_do_not_launch_cli():
    from agno.exceptions import UnsupportedMediaError
    from agno.media import Audio

    spawn = AsyncMock()
    agent = PrimeAgent()
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        result = await agent.arun({"prompt": "hello"})
        assert result.status == RunStatus.error
        assert "must be a string" in result.content
        with pytest.raises(UnsupportedMediaError):
            agent.arun("hello", audio=[Audio(content=b"audio")])
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_interrupts_cli_and_returns_cancelled():
    from agno.run.agent import RunCancelledEvent

    process = StubProcess([])
    process.returncode = None
    process.stdout = asyncio.StreamReader()
    delta = {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"}}
    process.stdout.feed_data(json.dumps(delta).encode() + b"\n")
    finished = asyncio.Event()

    async def wait():
        await finished.wait()
        return process.returncode

    def terminate(handle, **kwargs):
        assert handle is process
        process.returncode = -15
        process.stdout.feed_eof()
        finished.set()

    process.wait = wait
    agent = PrimeAgent()
    with (
        patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
        patch.object(agent, "_signal_process", side_effect=terminate) as stop,
    ):
        result = []
        async for event in agent.arun("hello", run_id="prime-cancel", stream=True, yield_run_output=True):
            result.append(event)
            if isinstance(event, RunContentEvent):
                await agent.acancel_run("prime-cancel")
    stop.assert_called_once()
    assert any(isinstance(event, RunCancelledEvent) for event in result)
    assert result[-1].status == RunStatus.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome, expected",
    [
        ({"result": {"summary": "context"}}, True),
        ({"errorMessage": "Nothing to compact", "errorSeverity": "warning"}, False),
    ],
)
async def test_native_compaction_uses_stored_session(outcome, expected):
    agent = PrimeAgent()
    agent._session_ids[("u1", "s1")] = "prime-1"
    spawn = AsyncMock(return_value=StubProcess([{"type": "compaction_end", **outcome}]))
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        assert await agent.acompact("s1", user_id="u1") is expected
    command = spawn.call_args.args
    assert command[command.index("--resume") + 1] == "prime-1"
    assert command[-1] == "/compact"
    assert not agent._sessions_in_flight


@pytest.mark.asyncio
async def test_compaction_missing_busy_and_failed():
    from agno.exceptions import SessionBusyError

    agent = PrimeAgent()
    spawn = AsyncMock()
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        assert await agent.acompact("s1") is False
        agent._session_ids[(None, "s1")] = "prime-1"
        agent._sessions_in_flight["s1"] = "active-run"
        with pytest.raises(SessionBusyError, match="in flight"):
            await agent.acompact("s1")
    spawn.assert_not_called()
    agent._sessions_in_flight.clear()
    spawn = AsyncMock(return_value=StubProcess([{"type": "compaction_end", "errorMessage": "failed"}]))
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        with pytest.raises(RuntimeError, match="failed"):
            await agent.acompact("s1")
    assert not agent._sessions_in_flight


def test_sync_compaction():
    agent = PrimeAgent()
    agent._session_ids[(None, "s1")] = "prime-1"

    async def spawn(*args, **kwargs):
        return StubProcess([{"type": "compaction_end", "result": {"summary": "context"}}])

    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        assert agent.compact("s1") is True


@pytest.mark.asyncio
async def test_native_configuration_is_forwarded(tmp_path):
    async def spawn(*args, **kwargs):
        for flag, value in (
            ("--provider", "anthropic"),
            ("--model", "m1"),
            ("--thinking", "high"),
            ("--system-prompt", "Base"),
            ("--append-system-prompt", "First\n\nSecond"),
            ("--cwd", str(tmp_path)),
            ("--session-dir", str(tmp_path / "sessions")),
        ):
            assert args[args.index(flag) + 1] == value
        assert args.count("--skill") == 2
        assert "--no-skills" in args
        assert kwargs["env"]["PRIME_TEST_VALUE"] == "configured"
        return StubProcess(answer_events())

    agent = PrimeAgent(
        provider="anthropic",
        model="m1",
        thinking="high",
        system_prompt="Base",
        instructions="First",
        append_system_prompt="Second",
        cwd=str(tmp_path),
        session_dir=str(tmp_path / "sessions"),
        skills=["/skills/a", "/skills/b"],
        no_skills=True,
        env={"PRIME_TEST_VALUE": "configured"},
    )
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", spawn):
        result = await agent.arun("hello")
    assert result.model == "m1"
    assert result.model_provider == "anthropic"


@pytest.mark.asyncio
async def test_error_json_is_not_silently_ignored():
    process = StubProcess([{"type": "error", "message": "provider unavailable"}])
    with patch("agno.agents.prime.agent.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await PrimeAgent().arun("hello")
    assert result.status == RunStatus.error
    assert result.content == "provider unavailable"

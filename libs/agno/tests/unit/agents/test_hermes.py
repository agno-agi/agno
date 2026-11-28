"""Hermes adapter regression cases using a fake native API; never import Hermes."""

import asyncio
from copy import deepcopy
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from agno.agents.hermes import HermesAgent
from agno.agents.hermes import agent as hermes_module
from agno.db.sqlite import SqliteDb
from agno.exceptions import UnsupportedMediaError
from agno.media import Image
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(
        options=[],
        calls=[],
        closed=[],
        interrupts=[],
        results=[],
        stream=True,
        tools=True,
        block=False,
        started=Event(),
        stop=Event(),
        threads=[],
    )

    class AIAgent:
        def __init__(self, **options):
            self.options = options
            state.options.append(options)
            state.threads.append(get_ident())

        def run_conversation(self, *, user_message, conversation_history, task_id):
            state.calls.append(dict(prompt=user_message, history=deepcopy(conversation_history), task_id=task_id))
            messages = deepcopy(conversation_history or [])
            boundary = len(messages)
            messages.append({"role": "user", "content": user_message})
            if state.tools:
                self.options["tool_start_callback"]("call-1", "terminal", {"command": "pwd"})
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "terminal",
                                        "arguments": '{"command":"pwd"}',
                                    },
                                },
                            ],
                        },
                        {"role": "tool", "tool_call_id": "call-1", "content": "/workspace"},
                    ]
                )
                self.options["tool_complete_callback"]("call-1", "terminal", {"command": "pwd"}, "/workspace")
            state.started.set()
            if state.block and not state.stop.wait(3):
                raise RuntimeError("Fake native worker was not interrupted")
            if state.stream:
                self.options["stream_delta_callback"]("Hello")
                self.options["stream_delta_callback"](" world")
            messages.append({"role": "assistant", "content": "Hello world"})
            result = dict(
                final_response="Hello world",
                messages=messages,
                completed=True,
                current_turn_user_idx=boundary,
                model="actual-model",
                provider="actual-provider",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost_usd=0.01,
                cost_status="estimated",
            )
            if state.results:
                result.update(state.results.pop(0))
            return result

        def interrupt(self):
            state.interrupts.append(self)
            state.stop.set()

        def close(self):
            state.closed.append(self)

    monkeypatch.setattr(hermes_module, "_sdk", lambda: SimpleNamespace(AIAgent=AIAgent))
    return state


def test_sync_run_and_constructor_options(native):
    caller_thread = get_ident()
    agent = HermesAgent(
        name="Hermes",
        model="requested-model",
        provider="openrouter",
        cwd="/workspace",
        instructions="Be concise",
        enabled_toolsets=[],
        native_options={"max_tokens": 100},
    )
    result = agent.run("hello")
    assert result.status == RunStatus.completed
    assert result.content == "Hello world"
    assert result.model == "actual-model"
    assert result.model_provider == "actual-provider"
    assert result.metrics.total_tokens == 15
    assert result.tools[0].result == "/workspace"
    assert native.options[0]["ephemeral_system_prompt"] == "Be concise"
    assert native.options[0]["enabled_toolsets"] == []
    assert native.options[0]["quiet_mode"] is True
    assert native.options[0]["skip_memory"] is True
    assert native.options[0]["max_tokens"] == 100
    assert native.threads[0] != caller_thread
    assert len(native.closed) == 1
    assert agent.sdk == "hermes"


@pytest.mark.asyncio
async def test_stream_tools_and_text_without_duplicate_final(native):
    events = [event async for event in HermesAgent(name="Hermes").arun("hello", stream=True)]
    assert "".join(event.content for event in events if isinstance(event, RunContentEvent)) == "Hello world"
    started = next(event for event in events if isinstance(event, ToolCallStartedEvent))
    completed = next(event for event in events if isinstance(event, ToolCallCompletedEvent))
    assert started.tool.tool_call_id == completed.tool.tool_call_id
    assert completed.tool.result == "/workspace"
    assert isinstance(events[-1], RunCompletedEvent)


@pytest.mark.asyncio
async def test_provider_without_deltas_emits_final(native):
    native.stream = False
    events = [event async for event in HermesAgent().arun("hello", stream=True)]
    assert "".join(event.content for event in events if isinstance(event, RunContentEvent)) == "Hello world"


@pytest.mark.asyncio
async def test_database_history_survives_adapter_recreation(native, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "hermes.db"))
    first = await HermesAgent(id="hermes", db=db).arun("hello", session_id="s", user_id="u")
    recreated = HermesAgent(id="hermes", db=db)
    second = await recreated.arun("again", session_id="s", user_id="u")
    assert first.status == second.status == RunStatus.completed
    assert native.options[0]["session_id"] == native.options[1]["session_id"]
    assert native.calls[1]["history"][-1]["content"] == "Hello world"
    assert any(message["role"] == "tool" for message in native.calls[1]["history"])
    assert len(second.tools) == 1
    assert second.metrics.total_tokens == 15


@pytest.mark.asyncio
async def test_memory_history_scoped_by_user_and_session(native):
    agent = HermesAgent()
    await agent.arun("first", session_id="s", user_id="one")
    await agent.arun("other user", session_id="s", user_id="two")
    await agent.arun("other session", session_id="other", user_id="one")
    await agent.arun("again", session_id="s", user_id="one")
    assert all(call["history"] is None for call in native.calls[:3])
    assert native.calls[3]["history"][0]["content"] == "first"
    assert native.options[0]["session_id"] == native.options[3]["session_id"]
    assert len({options["session_id"] for options in native.options[:3]}) == 3


def test_stale_history_and_wrong_user_are_rejected():
    agent = HermesAgent()
    session = AgentSession(
        session_id="s",
        user_id="one",
        session_data={
            "hermes_conversation": {"run_id": "deleted", "messages": [{"role": "user", "content": "stale"}]},
        },
    )
    assert agent._conversation_state(session, "s", "one", "new") == {}
    with pytest.raises(ValueError, match="different user"):
        agent._conversation_state(session, "s", "two", "new")


@pytest.mark.asyncio
async def test_native_failure_is_error_and_does_not_advance_history(native):
    native.results = [{"failed": True, "completed": False, "error": "bad credentials", "failure_retryable": False}]
    agent = HermesAgent(retries=2)
    events = [event async for event in agent.arun("hello", stream=True, session_id="s")]
    assert any(isinstance(event, RunErrorEvent) for event in events)
    assert len(native.calls) == 1
    assert agent._states == {}


@pytest.mark.asyncio
async def test_retryable_failure_uses_shared_retries(native):
    native.results = [{"failed": True, "completed": False, "error": "temporary", "failure_retryable": True}]
    result = await HermesAgent(retries=1, delay_between_retries=0).arun("hello")
    assert result.status == RunStatus.completed
    assert len(native.calls) == len(native.closed) == 2


@pytest.mark.asyncio
async def test_cancellation_interrupts_worker_and_keeps_event_loop_available(native):
    native.block = True
    native.results = [{"interrupted": True, "completed": False}]
    agent = HermesAgent()
    task = asyncio.create_task(agent.arun("wait", run_id="hermes-cancel", session_id="s"))
    assert await asyncio.to_thread(native.started.wait, 2)
    await agent.acancel_run("hermes-cancel")
    result = await asyncio.wait_for(task, 3)
    assert result.status == RunStatus.cancelled
    assert native.interrupts
    assert len(native.closed) == 1
    assert agent._states == {}


@pytest.mark.asyncio
async def test_closing_stream_interrupts_native_worker(native):
    native.block = True
    agent = HermesAgent()
    events = agent._arun_adapter_stream("wait", run_id="close", session_id="s")
    assert isinstance(await asyncio.wait_for(events.__anext__(), 2), ToolCallStartedEvent)
    await asyncio.wait_for(events.aclose(), 3)
    assert native.interrupts
    assert len(native.closed) == 1


def test_transcript_recovers_tools_without_callbacks():
    result = {
        "current_turn_user_idx": 2,
        "messages": [
            {"role": "assistant", "tool_calls": [{"id": "old", "function": {"name": "terminal"}}]},
            {"role": "tool", "tool_call_id": "old", "content": "old result"},
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "new",
                        "function": {
                            "name": "terminal",
                            "arguments": '{"command":"pwd"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "new", "content": '{"error":"blocked"}'},
        ],
    }
    tools = HermesAgent._result_tools(result, "hello", {})
    assert len(tools) == 1
    assert tools[0].tool_call_id == "new"
    assert tools[0].tool_call_error is True


@pytest.mark.parametrize("options", [{"quiet_mode": False}, {"session_id": "unsafe"}, {"stream_delta_callback": None}])
def test_reserved_native_options(options):
    with pytest.raises(ValueError, match="cannot override"):
        HermesAgent(native_options=options)


def test_unsupported_configuration():
    with pytest.raises(ValueError, match="max_iterations"):
        HermesAgent(max_iterations=0)
    with pytest.raises(ValueError, match="output_schema"):
        HermesAgent(output_schema={"type": "object"})
    with pytest.raises(UnsupportedMediaError, match="images"):
        HermesAgent().run("hello", images=[Image(url="https://example.com/image.png")])


def test_transcript_reconciliation_does_not_mutate_tool_start():
    started = ToolExecution(tool_call_id="call-1", tool_name="terminal", tool_args={"command": "pwd"})
    result = {
        "current_turn_user_idx": 0,
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {"name": "terminal"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": '{"error":"blocked"}'},
        ],
    }
    completed = HermesAgent._result_tools(result, "hello", {"call-1": started})
    assert completed[0].tool_call_error is True
    assert started.result is None
    assert started.tool_call_error is not True

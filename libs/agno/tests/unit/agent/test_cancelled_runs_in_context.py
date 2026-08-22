"""Unit tests for Agent.add_cancelled_runs_to_context.

Builds run messages offline (no model call) and asserts that the param includes a
cancelled run's partial content in history and closes its dangling tool call, while
paused/errored runs stay excluded. Default behavior (flag off) excludes cancelled runs.
"""

import pytest

from agno.agent._messages import aget_run_messages, get_run_messages
from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _cancelled_run() -> RunOutput:
    return RunOutput(
        run_id="cancelled_1",
        session_id="s",
        status=RunStatus.cancelled,
        content="Let me look up the GPU prices.",
        messages=[
            Message(role="user", content="Find the price of the RTX 4090."),
            Message(
                role="assistant",
                content="Let me look up the GPU prices.",
                tool_calls=[
                    {"id": "tc_partial", "type": "function", "function": {"name": "search", "arguments": "{}"}}
                ],
            ),
            # cancelled before the tool returned -> dangling tool call
        ],
    )


def _run_with_status(run_id: str, status: RunStatus, marker: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        session_id="s",
        status=status,
        messages=[Message(role="user", content=marker), Message(role="assistant", content="partial")],
    )


def _build(flag: bool, runs):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), add_history_to_context=True, add_cancelled_runs_to_context=flag)
    session = AgentSession(session_id="s", runs=runs)
    return get_run_messages(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        input="hello",
        session=session,
        add_history_to_context=True,
    )


def _history(run_messages):
    return [m for m in run_messages.messages if getattr(m, "from_history", False)]


def test_flag_on_includes_cancelled_and_closes_tool_call():
    history = _history(_build(True, [_cancelled_run()]))
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    # dangling tool call closed with a synthetic result
    synthetic = [m for m in history if m.role == "tool" and m.tool_call_id == "tc_partial"]
    assert len(synthetic) == 1
    assert synthetic[0].content == '{"status": "cancelled"}'


def test_flag_off_excludes_cancelled():
    history = _history(_build(False, [_cancelled_run()]))
    assert all("RTX 4090" not in (m.content or "") for m in history)
    assert all(m.tool_call_id != "tc_partial" for m in history)


def test_flag_on_still_excludes_paused_and_error():
    runs = [
        _run_with_status("paused_1", RunStatus.paused, "PAUSED_MARKER"),
        _run_with_status("error_1", RunStatus.error, "ERROR_MARKER"),
        _cancelled_run(),
    ]
    history = _history(_build(True, runs))
    contents = " ".join(str(m.content or "") for m in history)
    assert "PAUSED_MARKER" not in contents
    assert "ERROR_MARKER" not in contents
    assert "RTX 4090" in contents  # only cancelled is un-skipped


@pytest.mark.asyncio
async def test_flag_on_async_includes_cancelled():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), add_history_to_context=True, add_cancelled_runs_to_context=True)
    session = AgentSession(session_id="s", runs=[_cancelled_run()])
    run_messages = await aget_run_messages(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        input="hello",
        session=session,
        add_history_to_context=True,
    )
    history = [m for m in run_messages.messages if getattr(m, "from_history", False)]
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    assert any(m.role == "tool" and m.tool_call_id == "tc_partial" for m in history)


def test_default_param_is_false():
    assert Agent(model=OpenAIChat(id="gpt-4o-mini")).add_cancelled_runs_to_context is False


def test_serialization_round_trip_preserves_flag():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), add_history_to_context=True, add_cancelled_runs_to_context=True)
    restored = Agent.from_dict(agent.to_dict())
    assert restored.add_cancelled_runs_to_context is True

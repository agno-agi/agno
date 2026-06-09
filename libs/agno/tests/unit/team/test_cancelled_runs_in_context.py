"""Unit tests for Team.add_cancelled_runs_to_context.

Builds the team leader's run messages offline (no model call) and asserts that the
param includes a cancelled team run's partial content and closes its dangling
tool call, while paused/errored runs stay excluded. Default (flag off) excludes them.
"""

import pytest

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages
from agno.team._run import _get_continue_run_messages
from agno.team._tools import _get_history_for_member_agent
from agno.team.team import Team


def _cancelled_run() -> TeamRunOutput:
    return TeamRunOutput(
        run_id="cancelled_1",
        session_id="s",
        parent_run_id=None,
        status=RunStatus.cancelled,
        content="Let me delegate the GPU price lookup.",
        messages=[
            Message(role="user", content="Find the price of the RTX 4090."),
            Message(
                role="assistant",
                content="Let me delegate the GPU price lookup.",
                tool_calls=[
                    {"id": "tc_partial", "type": "function", "function": {"name": "delegate", "arguments": "{}"}}
                ],
            ),
            # cancelled before the member returned -> dangling tool call
        ],
    )


def _run_with_status(run_id: str, status: RunStatus, marker: str) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        session_id="s",
        parent_run_id=None,
        status=status,
        messages=[Message(role="user", content=marker), Message(role="assistant", content="partial")],
    )


def _make_team(flag: bool) -> Team:
    return Team(
        members=[Agent(name="M", model=OpenAIChat(id="gpt-4o-mini"))],
        model=OpenAIChat(id="gpt-4o-mini"),
        add_history_to_context=True,
        add_cancelled_runs_to_context=flag,
    )


def _build(flag: bool, runs):
    session = TeamSession(session_id="s", runs=runs)
    return _get_run_messages(
        _make_team(flag),
        run_response=TeamRunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=session,
        input_message="hello",
        add_history_to_context=True,
    )


def _history(run_messages):
    return [m for m in run_messages.messages if getattr(m, "from_history", False)]


def test_flag_on_includes_cancelled_and_closes_tool_call():
    history = _history(_build(True, [_cancelled_run()]))
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    synthetic = [m for m in history if m.role == "tool" and m.tool_call_id == "tc_partial"]
    assert len(synthetic) == 1
    assert synthetic[0].content == '{"status": "cancelled"}'


def test_flag_off_excludes_cancelled():
    history = _history(_build(False, [_cancelled_run()]))
    assert all("RTX 4090" not in (m.content or "") for m in history)


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
    assert "RTX 4090" in contents


@pytest.mark.asyncio
async def test_flag_on_async_includes_cancelled():
    session = TeamSession(session_id="s", runs=[_cancelled_run()])
    run_messages = await _aget_run_messages(
        _make_team(True),
        run_response=TeamRunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=session,
        input_message="hello",
        add_history_to_context=True,
    )
    history = [m for m in run_messages.messages if getattr(m, "from_history", False)]
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    assert any(m.role == "tool" and m.tool_call_id == "tc_partial" for m in history)


def test_continue_run_flag_on_includes_cancelled():
    """Team continue-run history builder (in team/_run.py) must honor the param too."""
    session = TeamSession(session_id="s", runs=[_cancelled_run()])
    run_messages = _get_continue_run_messages(
        _make_team(True),
        input=[Message(role="user", content="continue")],
        session=session,
        add_history_to_context=True,
        run_context=RunContext(run_id="r", session_id="s"),
    )
    history = [m for m in run_messages.messages if getattr(m, "from_history", False)]
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    assert any(m.role == "tool" and m.tool_call_id == "tc_partial" for m in history)


def test_continue_run_flag_off_excludes_cancelled():
    session = TeamSession(session_id="s", runs=[_cancelled_run()])
    run_messages = _get_continue_run_messages(
        _make_team(False),
        input=[Message(role="user", content="continue")],
        session=session,
        add_history_to_context=True,
        run_context=RunContext(run_id="r", session_id="s"),
    )
    history = [m for m in run_messages.messages if getattr(m, "from_history", False)]
    assert all("RTX 4090" not in (m.content or "") for m in history)


def test_default_param_is_false():
    team = Team(members=[Agent(name="M", model=OpenAIChat(id="gpt-4o-mini"))], model=OpenAIChat(id="gpt-4o-mini"))
    assert team.add_cancelled_runs_to_context is False


def test_serialization_round_trip_preserves_flag():
    team = _make_team(True)
    restored = Team.from_dict(team.to_dict())
    assert restored.add_cancelled_runs_to_context is True


def _cancelled_member_run(agent_id: str) -> RunOutput:
    return RunOutput(
        run_id="member_cancelled_1",
        session_id="s",
        agent_id=agent_id,
        parent_run_id="team_run_1",
        status=RunStatus.cancelled,
        messages=[
            Message(role="user", content="Find the price of the RTX 4090."),
            Message(
                role="assistant",
                content="Checking prices.",
                tool_calls=[{"id": "tc_member", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
            ),
            # cancelled before the tool returned -> dangling tool call
        ],
    )


def test_member_history_honors_member_flag():
    """The member-history path used during team delegation must honor the member's own param."""
    member = Agent(
        id="member_1",
        name="M",
        model=OpenAIChat(id="gpt-4o-mini"),
        add_history_to_context=True,
        add_cancelled_runs_to_context=True,
    )
    team = Team(members=[member], model=OpenAIChat(id="gpt-4o-mini"))
    session = TeamSession(session_id="s", runs=[_cancelled_member_run("member_1")])
    history = _get_history_for_member_agent(team, session, member)
    assert any(m.role == "user" and "RTX 4090" in (m.content or "") for m in history)
    assert any(m.role == "tool" and m.tool_call_id == "tc_member" for m in history)


def test_member_history_excludes_cancelled_by_default():
    member = Agent(id="member_1", name="M", model=OpenAIChat(id="gpt-4o-mini"), add_history_to_context=True)
    team = Team(members=[member], model=OpenAIChat(id="gpt-4o-mini"))
    session = TeamSession(session_id="s", runs=[_cancelled_member_run("member_1")])
    history = _get_history_for_member_agent(team, session, member)
    assert history == []

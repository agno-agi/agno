"""Unit tests for Team.include_member_messages_in_history (issue #7918)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from agno.models.message import Message
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages
from agno.team.team import Team

TEAM_RUN_ID = "team-run-1"
MEMBER_MARKER = "Member SQL result"
LEADER_MARKER = "Team leader response"


def _session_with_leader_and_member() -> TeamSession:
    return TeamSession(
        session_id=str(uuid4()),
        team_id="test-team",
        runs=[
            TeamRunOutput(
                run_id=TEAM_RUN_ID,
                team_id="test-team",
                status=RunStatus.completed,
                parent_run_id=None,
                messages=[
                    Message(role="user", content="What SQL did we run?"),
                    Message(role="assistant", content=LEADER_MARKER),
                ],
            ),
            RunOutput(
                run_id="member-run-1",
                agent_id="sql-agent",
                parent_run_id=TEAM_RUN_ID,
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Run SELECT 1"),
                    Message(role="assistant", content=MEMBER_MARKER),
                ],
            ),
        ],
    )


def _history_contents(run_messages) -> list[str]:
    return [m.content for m in run_messages.messages if getattr(m, "from_history", False) and m.content]


@pytest.fixture
def session_with_runs():
    return _session_with_leader_and_member()


@pytest.fixture
def run_context():
    return RunContext(run_id="current-run", session_id="session-1")


@pytest.fixture
def run_response():
    return TeamRunOutput(run_id="current-run", team_id="test-team")


def test_default_excludes_member_messages_in_team_history(session_with_runs, run_context, run_response):
    team = Team(id="test-team", members=[], add_history_to_context=True)

    with patch.object(team, "get_system_message", return_value=None):
        run_messages = _get_run_messages(
            team,
            run_response=run_response,
            run_context=run_context,
            session=session_with_runs,
            input_message="Follow up",
            add_history_to_context=True,
        )

    history = _history_contents(run_messages)
    assert len(history) == 2
    assert LEADER_MARKER in history
    assert MEMBER_MARKER not in history


@pytest.mark.asyncio
async def test_async_default_excludes_member_messages_in_team_history(session_with_runs, run_context, run_response):
    team = Team(id="test-team", members=[], add_history_to_context=True)

    with patch.object(team, "aget_system_message", return_value=None):
        run_messages = await _aget_run_messages(
            team,
            run_response=run_response,
            run_context=run_context,
            session=session_with_runs,
            input_message="Follow up",
            add_history_to_context=True,
        )

    history = _history_contents(run_messages)
    assert len(history) == 2
    assert LEADER_MARKER in history
    assert MEMBER_MARKER not in history


def test_include_member_messages_in_history_adds_member_runs(session_with_runs, run_context, run_response):
    team = Team(
        id="test-team",
        members=[],
        add_history_to_context=True,
        include_member_messages_in_history=True,
    )

    with patch.object(team, "get_system_message", return_value=None):
        run_messages = _get_run_messages(
            team,
            run_response=run_response,
            run_context=run_context,
            session=session_with_runs,
            input_message="Follow up",
            add_history_to_context=True,
        )

    history = _history_contents(run_messages)
    assert len(history) == 4
    assert LEADER_MARKER in history
    assert MEMBER_MARKER in history


@pytest.mark.asyncio
async def test_async_path_includes_member_messages_when_enabled(session_with_runs, run_context, run_response):
    team = Team(
        id="test-team",
        members=[],
        add_history_to_context=True,
        include_member_messages_in_history=True,
    )

    with patch.object(team, "aget_system_message", return_value=None):
        run_messages = await _aget_run_messages(
            team,
            run_response=run_response,
            run_context=run_context,
            session=session_with_runs,
            input_message="Follow up",
            add_history_to_context=True,
        )

    history = _history_contents(run_messages)
    assert len(history) == 4
    assert LEADER_MARKER in history
    assert MEMBER_MARKER in history


def test_add_history_to_context_false_loads_no_history(session_with_runs, run_context, run_response):
    team = Team(
        id="test-team",
        members=[],
        include_member_messages_in_history=True,
    )

    with patch.object(team, "get_system_message", return_value=None):
        run_messages = _get_run_messages(
            team,
            run_response=run_response,
            run_context=run_context,
            session=session_with_runs,
            input_message="Follow up",
            add_history_to_context=False,
        )

    assert _history_contents(run_messages) == []


def test_include_member_messages_default_is_false():
    team = Team(id="default-team", members=[])
    assert team.include_member_messages_in_history is False


def test_include_member_messages_serialized_when_true():
    team = Team(
        id="serialize-team",
        members=[],
        include_member_messages_in_history=True,
    )
    config = team.to_dict()
    assert config["include_member_messages_in_history"] is True


def test_include_member_messages_omitted_from_config_when_false():
    team = Team(id="omit-team", members=[])
    assert "include_member_messages_in_history" not in team.to_dict()


def test_from_dict_roundtrip_preserves_include_member_messages_in_history():
    """Test that to_dict -> from_dict preserves include_member_messages_in_history."""
    team = Team(
        id="rt-team",
        members=[],
        add_history_to_context=True,
        include_member_messages_in_history=True,
    )
    config = team.to_dict()
    reconstructed = Team.from_dict(config)

    assert reconstructed.include_member_messages_in_history is True
    assert reconstructed.add_history_to_context is True

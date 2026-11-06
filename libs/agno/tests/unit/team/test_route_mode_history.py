import pytest

from agno.agent import Agent
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.summary import SessionSummaryManager
from agno.session.team import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages
from agno.team.team import Team


class _DummySummaryModel:
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False


def _build_route_like_session(team_id: str) -> TeamSession:
    member_run = RunOutput(
        run_id="run-member-1",
        agent_id="member-1",
        parent_run_id="run-team-1",
        status=RunStatus.completed,
        messages=[Message(role="assistant", content="Member final answer")],
    )
    team_run = TeamRunOutput(
        run_id="run-team-1",
        team_id=team_id,
        status=RunStatus.completed,
        messages=[Message(role="user", content="User question")],
        member_responses=[member_run],
    )
    session = TeamSession(session_id="session-1", team_id=team_id, runs=[])
    session.upsert_run(team_run)
    session.upsert_run(member_run)
    return session


def test_route_mode_history_replay_includes_member_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    team = Team(name="route-team", id="team-1", members=[Agent(name="member-1")], respond_directly=True)
    session = _build_route_like_session(team.id)
    run_context = RunContext(run_id="run-new", session_id=session.session_id, session_state={})
    run_response = TeamRunOutput(run_id="run-new", team_id=team.id, status=RunStatus.running)

    monkeypatch.setattr(
        team,
        "get_system_message",
        lambda **kwargs: Message(role="system", content="system"),
    )

    run_messages = _get_run_messages(
        team,
        run_response=run_response,
        run_context=run_context,
        session=session,
        input_message="new input",
        add_history_to_context=True,
    )

    history_assistant_contents = [
        m.content for m in run_messages.messages if getattr(m, "from_history", False) and m.role == "assistant"
    ]
    assert "Member final answer" in history_assistant_contents


@pytest.mark.asyncio
async def test_route_mode_async_history_replay_includes_member_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    team = Team(name="route-team-async", id="team-2", members=[Agent(name="member-1")], respond_directly=True)
    session = _build_route_like_session(team.id)
    run_context = RunContext(run_id="run-new", session_id=session.session_id, session_state={})
    run_response = TeamRunOutput(run_id="run-new", team_id=team.id, status=RunStatus.running)

    async def _fake_async_system_message(**kwargs):
        return Message(role="system", content="system")

    monkeypatch.setattr(team, "aget_system_message", _fake_async_system_message)

    run_messages = await _aget_run_messages(
        team,
        run_response=run_response,
        run_context=run_context,
        session=session,
        input_message="new input",
        add_history_to_context=True,
    )

    history_assistant_contents = [
        m.content for m in run_messages.messages if getattr(m, "from_history", False) and m.role == "assistant"
    ]
    assert "Member final answer" in history_assistant_contents


def test_coordinate_mode_history_replay_still_excludes_member_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    team = Team(name="coordinate-team", id="team-3", members=[Agent(name="member-1")], respond_directly=False)
    session = _build_route_like_session(team.id)
    run_context = RunContext(run_id="run-new", session_id=session.session_id, session_state={})
    run_response = TeamRunOutput(run_id="run-new", team_id=team.id, status=RunStatus.running)

    monkeypatch.setattr(
        team,
        "get_system_message",
        lambda **kwargs: Message(role="system", content="system"),
    )

    run_messages = _get_run_messages(
        team,
        run_response=run_response,
        run_context=run_context,
        session=session,
        input_message="new input",
        add_history_to_context=True,
    )

    history_assistant_contents = [
        m.content for m in run_messages.messages if getattr(m, "from_history", False) and m.role == "assistant"
    ]
    assert "Member final answer" not in history_assistant_contents


def test_summary_manager_passes_skip_member_messages_only_for_team_like_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agno.session.summary as summary_module

    monkeypatch.setattr(summary_module, "get_model", lambda _model: _DummySummaryModel())

    manager = SessionSummaryManager(model="noop:model", skip_member_messages=False)

    team_session = TeamSession(session_id="team-session")
    team_kwargs = {}

    def _team_get_messages(**kwargs):
        team_kwargs.update(kwargs)
        return [Message(role="user", content="u"), Message(role="assistant", content="a")]

    monkeypatch.setattr(team_session, "get_messages", _team_get_messages)
    prepared = manager._prepare_summary_messages(team_session)
    assert prepared is not None
    assert team_kwargs.get("skip_member_messages") is False

    agent_session = AgentSession(session_id="agent-session")
    agent_kwargs = {}

    def _agent_get_messages(**kwargs):
        agent_kwargs.update(kwargs)
        return [Message(role="user", content="u"), Message(role="assistant", content="a")]

    monkeypatch.setattr(agent_session, "get_messages", _agent_get_messages)
    prepared = manager._prepare_summary_messages(agent_session)
    assert prepared is not None
    assert "skip_member_messages" not in agent_kwargs

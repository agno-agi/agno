from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent.remote import RemoteAgent
from agno.team.remote import RemoteTeam


def test_remote_team_exposes_knowledge_filter_attributes() -> None:
    remote_team = RemoteTeam.__new__(RemoteTeam)
    remote_team.agentos_client = None

    assert remote_team.knowledge_filters is None
    assert remote_team.enable_agentic_knowledge_filters is False
    assert (not remote_team.knowledge_filters and remote_team.knowledge) is None


@pytest.mark.asyncio
async def test_remote_agent_a2a_forwards_metadata() -> None:
    """RemoteAgent.arun(protocol="a2a") must forward `metadata` to the A2A client.

    Regression test: metadata was accepted by arun()'s signature but silently
    dropped before reaching a2a_client.send_message/stream_message.
    """
    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="test_agent", protocol="a2a")

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value=MagicMock())
    remote_agent.a2a_client = mock_client

    await remote_agent.arun(
        "hello",
        stream=False,
        user_id="user-123",
        session_id="session-abc",
        metadata={"company_id": "C-1", "investor_company_id": "IC-1"},
        auth_token="jwt-token-here",
    )

    mock_client.send_message.assert_called_once()
    assert mock_client.send_message.call_args.kwargs["metadata"] == {
        "company_id": "C-1",
        "investor_company_id": "IC-1",
    }


@pytest.mark.asyncio
async def test_remote_team_a2a_forwards_metadata() -> None:
    """RemoteTeam.arun(protocol="a2a") must forward `metadata` to the A2A client.

    Regression test: same drop as RemoteAgent, mirrored in RemoteTeam._arun_a2a.
    """
    remote_team = RemoteTeam(base_url="http://fake-host", team_id="test_team", protocol="a2a")

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value=MagicMock())
    remote_team.a2a_client = mock_client

    await remote_team.arun(
        "hello",
        stream=False,
        user_id="user-123",
        session_id="session-abc",
        metadata={"company_id": "C-1", "investor_company_id": "IC-1"},
        auth_token="jwt-token-here",
    )

    mock_client.send_message.assert_called_once()
    assert mock_client.send_message.call_args.kwargs["metadata"] == {
        "company_id": "C-1",
        "investor_company_id": "IC-1",
    }


def test_remote_agent_role_is_a_property() -> None:
    """RemoteAgent.role must resolve to the configured role string, not a bound method.

    Regression test: the missing @property meant a Team leader's system prompt
    interpolated the bound-method repr for every remote member.
    """
    from agno.os.routers.agents.schema import AgentResponse

    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="greeter")
    remote_agent._cached_agent_config = (
        AgentResponse(id="greeter", name="Greeter", role="Greets users warmly"),
        float("inf"),
    )
    assert remote_agent.role == "Greets users warmly"
    assert isinstance(remote_agent.role, str)


def test_remote_team_role_is_a_property() -> None:
    """RemoteTeam.role must resolve to the configured role string, not a bound method."""
    from agno.os.routers.teams.schema import TeamResponse

    remote_team = RemoteTeam(base_url="http://fake-host", team_id="research")
    remote_team._cached_team_config = (
        TeamResponse(id="research", name="Research", role="Coordinates research tasks"),
        float("inf"),
    )
    assert remote_team.role == "Coordinates research tasks"
    assert isinstance(remote_team.role, str)


@pytest.mark.asyncio
async def test_remote_agent_stream_ends_with_its_run_output_when_asked() -> None:
    """RemoteAgent.arun(yield_run_output=True) never forwards the flag, and ends a failed stream with its run output,
    as a local agent does."""
    from agno.run.agent import RunErrorEvent, RunOutput
    from agno.run.base import RunStatus

    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="test_agent")

    async def _events():
        yield RunErrorEvent(run_id="run-1", session_id="s-1", agent_id="test_agent", content="boom")

    mock_client = MagicMock()
    mock_client.run_agent_stream = MagicMock(return_value=_events())
    remote_agent.agentos_client = mock_client

    stream = remote_agent.arun("hello", stream=True, yield_run_output=True)
    items = [item async for item in stream]

    assert "yield_run_output" not in mock_client.run_agent_stream.call_args.kwargs
    assert isinstance(items[-1], RunOutput)
    assert (items[-1].run_id, items[-1].status) == ("run-1", RunStatus.error)


@pytest.mark.asyncio
async def test_remote_agent_stream_ends_at_the_first_event_that_ends_its_own_run() -> None:
    """A sub-run's completion does not end the stream; a cancelled remote run that also sends a completed event ends
    cancelled: the first event that ends the run itself is its final status. The run output keeps the model its
    started event names."""
    from agno.run.agent import RunCancelledEvent, RunCompletedEvent, RunOutput, RunStartedEvent
    from agno.run.base import RunStatus

    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="test_agent")

    async def _events():
        yield RunStartedEvent(
            run_id="run-1", session_id="s-1", agent_id="test_agent", model="gpt-5.6-luna", model_provider="OpenAI"
        )
        yield RunCompletedEvent(run_id="sub-run-1", session_id="s-1", agent_id="sub_agent")
        yield RunCancelledEvent(run_id="run-1", session_id="s-1", agent_id="test_agent")
        yield RunCompletedEvent(run_id="run-1", session_id="s-1", agent_id="test_agent")

    items = [item async for item in remote_agent._with_run_output(_events())]

    assert [type(item) for item in items] == [RunStartedEvent, RunCompletedEvent, RunCancelledEvent, RunOutput]
    assert (items[-1].run_id, items[-1].status) == ("run-1", RunStatus.cancelled)
    # The run's model, named only by its started event
    assert (items[-1].model, items[-1].model_provider) == ("gpt-5.6-luna", "OpenAI")


@pytest.mark.asyncio
async def test_remote_team_stream_run_output_keeps_its_member_responses() -> None:
    """A RemoteTeam's run output keeps the member runs its completed event carries, so the local team counts them."""
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput
    from agno.run.team import RunCompletedEvent, TeamRunOutput

    remote_team = RemoteTeam(base_url="http://fake-host", team_id="test_team")
    member_run = RunOutput(run_id="member-run", agent_id="member", metrics=RunMetrics(total_tokens=32))

    async def _events():
        yield RunCompletedEvent(run_id="run-1", session_id="s-1", team_id="test_team", member_responses=[member_run])

    items = [item async for item in remote_team._with_run_output(_events())]

    assert isinstance(items[-1], TeamRunOutput)
    assert items[-1].member_responses == [member_run]


def test_remote_member_runs_in_a_session_of_its_own() -> None:
    """A remote member keeps its own session on its AgentOS; a local member shares the team's."""
    from agno.agent import Agent
    from agno.utils.team import get_member_session_id

    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="remote_agent")

    assert get_member_session_id(remote_agent, "team-session") == "team-session:remote_agent"
    assert get_member_session_id(Agent(name="local"), "team-session") == "team-session"


def test_remote_members_run_is_stored_by_the_agentos_that_ran_it(monkeypatch) -> None:
    """The team stores its local members' runs, and leaves a remote member's run, kept in the member's own session, to
    the AgentOS that ran it, so a shared database keeps it in the member's history."""
    from agno.run.agent import RunOutput
    from agno.session import TeamSession
    from agno.team import Team
    from agno.team._run import _persist_member_runs_for_team_run

    session = TeamSession(
        session_id="team-session",
        runs=[
            RunOutput(run_id="local-run", session_id="team-session", parent_run_id="team-run"),
            RunOutput(run_id="remote-run", session_id="team-session:remote_agent", parent_run_id="team-run"),
        ],
    )
    saved_run_ids = []
    monkeypatch.setattr("agno.team._session.save_run", lambda team, run, **kwargs: saved_run_ids.append(run.run_id))

    _persist_member_runs_for_team_run(Team(members=[]), session, "team-run")

    assert saved_run_ids == ["local-run"]


def test_continued_remote_member_keeps_its_team_run() -> None:
    """A remote continue stream names neither the model nor the team run, so both come from the paused copy."""
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.team._run import _replace_member_response

    paused = RunOutput(run_id="remote-run", parent_run_id="team-run", model="gpt-5.6-luna", model_provider="OpenAI")
    team_run = TeamRunOutput(run_id="team-run", member_responses=[paused])

    _replace_member_response(team_run, RunOutput(run_id="remote-run", content="done"))

    continued = team_run.member_responses[0]
    assert (continued.content, continued.parent_run_id, continued.model) == ("done", "team-run", "gpt-5.6-luna")


def test_stored_team_run_keeps_its_remote_members_metrics() -> None:
    """A team run stored without its member responses keeps the ids, model and metrics of its remote member's run,
    which the team's database may hold no other record of, and nothing else of it."""
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.run.team import TeamRunOutput
    from agno.team import Team
    from agno.team._session import _scrub_member_responses_keeping_paused

    remote_run = RunOutput(
        run_id="remote-run",
        session_id="team-session:remote_agent",
        parent_run_id="team-run",
        agent_id="remote_agent",
        content="remote answer",
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        metrics=RunMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
        status=RunStatus.completed,
    )
    team_run = TeamRunOutput(
        run_id="team-run",
        session_id="team-session",
        member_responses=[
            RunOutput(run_id="local-run", session_id="team-session", parent_run_id="team-run", content="local answer"),
            remote_run,
        ],
    )

    storage_run = _scrub_member_responses_keeping_paused(Team(members=[]), team_run)

    [stored_remote_run] = storage_run.member_responses
    assert (stored_remote_run.run_id, stored_remote_run.parent_run_id, stored_remote_run.agent_id) == (
        "remote-run",
        "team-run",
        "remote_agent",
    )
    assert (stored_remote_run.model, stored_remote_run.status) == ("gpt-5.6-luna", RunStatus.completed)
    assert stored_remote_run.metrics.total_tokens == 15
    assert stored_remote_run.content is None
    # The live run the caller holds keeps both members' whole runs
    assert len(team_run.member_responses) == 2 and remote_run.content == "remote answer"

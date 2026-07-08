import time
from unittest.mock import AsyncMock

import pytest

from agno.os.routers.teams.schema import TeamResponse
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.remote import RemoteTeam
from agno.team.team import Team


def test_remote_team_exposes_knowledge_filter_attributes() -> None:
    remote_team = RemoteTeam.__new__(RemoteTeam)
    remote_team.agentos_client = None

    assert remote_team.knowledge_filters is None
    assert remote_team.enable_agentic_knowledge_filters is False
    assert (not remote_team.knowledge_filters and remote_team.knowledge) is None


def _make_remote_team() -> RemoteTeam:
    remote_team = RemoteTeam(base_url="http://example.invalid", team_id="remote-team")
    remote_team._cached_team_config = (
        TeamResponse(id="remote-team", name="Remote Team", description="Delegates to a remote team"),
        time.time(),
    )
    return remote_team


def _make_delegate_function(remote_team: RemoteTeam, *, stream: bool = False):
    team = Team(id="local-team", members=[remote_team])
    return team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(run_id="parent-run", team_id="local-team"),
        run_context=RunContext(session_state={}, run_id="parent-run", session_id="test-session"),
        team_run_context={},
        stream=stream,
        async_mode=True,
    )


@pytest.mark.asyncio
async def test_async_delegate_to_remote_team_member() -> None:
    remote_team = _make_remote_team()
    remote_team.arun = AsyncMock(
        return_value=TeamRunOutput(run_id="remote-run", team_id="remote-team", content="remote answer")
    )

    delegate_function = _make_delegate_function(remote_team)

    response = [
        item
        async for item in delegate_function.entrypoint(member_id="remote-team", task="Ask the remote team")  # type: ignore[misc]
    ]

    assert response == ["remote answer"]
    remote_team.arun.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_stream_delegate_awaits_remote_team_stream_coroutine() -> None:
    remote_team = _make_remote_team()

    async def remote_stream():
        yield TeamRunOutput(run_id="remote-stream-run", team_id="remote-team", content="streamed answer")

    async def remote_arun(**kwargs):
        return remote_stream()

    remote_team.arun = remote_arun  # type: ignore[method-assign]

    delegate_function = _make_delegate_function(remote_team, stream=True)

    response = [
        item
        async for item in delegate_function.entrypoint(member_id="remote-team", task="Ask the remote team")  # type: ignore[misc]
    ]

    assert response == []

"""Tests for followup suggestions on teams.

Validates that team followups are returned as a flat List[str].
"""

import pytest

from agno.models.openai.chat import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team, TeamRunEvent

PROMPT = "What is the capital of France?"


def _make_team(**kwargs) -> Team:
    return Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        followups=True,
        num_followups=3,
        telemetry=False,
        **kwargs,
    )


def test_team_followups_sync():
    """Sync non-streaming: team followups should be a flat list of strings."""
    team = _make_team()
    response: TeamRunOutput = team.run(PROMPT)

    assert response.content is not None
    assert response.followups is not None
    assert isinstance(response.followups, list)
    assert len(response.followups) > 0
    for item in response.followups:
        assert isinstance(item, str)


def test_team_followups_sync_stream():
    """Sync streaming: followups_completed event should carry a flat list."""
    team = _make_team()
    followups_from_event = None

    for event in team.run(PROMPT, stream=True, stream_events=True):
        if event.event == TeamRunEvent.followups_completed:
            followups_from_event = event.followups  # type: ignore

    assert followups_from_event is not None
    assert isinstance(followups_from_event, list)
    for item in followups_from_event:
        assert isinstance(item, str)


@pytest.mark.asyncio
async def test_team_followups_async():
    """Async non-streaming: team followups should be a flat list of strings."""
    team = _make_team()
    response: TeamRunOutput = await team.arun(PROMPT)

    assert response.content is not None
    assert response.followups is not None
    assert isinstance(response.followups, list)
    assert len(response.followups) > 0
    for item in response.followups:
        assert isinstance(item, str)


@pytest.mark.asyncio
async def test_team_followups_async_stream():
    """Async streaming: followups_completed event should carry a flat list."""
    team = _make_team()
    followups_from_event = None

    async for event in team.arun(PROMPT, stream=True, stream_events=True):
        if event.event == TeamRunEvent.followups_completed:
            followups_from_event = event.followups  # type: ignore

    assert followups_from_event is not None
    assert isinstance(followups_from_event, list)
    for item in followups_from_event:
        assert isinstance(item, str)


def test_team_followups_to_dict_flat():
    """TeamRunOutput.to_dict() should serialize followups as a flat list."""
    team = _make_team()
    response: TeamRunOutput = team.run(PROMPT)

    assert response.followups is not None

    d = response.to_dict()
    assert "followups" in d
    assert isinstance(d["followups"], list)
    for item in d["followups"]:
        assert isinstance(item, str)

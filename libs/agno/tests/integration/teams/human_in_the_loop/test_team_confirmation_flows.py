"""Integration tests for team HITL confirmation flows.

Tests sync/async/streaming confirmation and rejection of member agent tools.
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


def _make_agent(db=None):
    return Agent(
        name="Weather Agent",
        role="Provides weather information. Use the get_the_weather tool to get weather data.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=db,
        telemetry=False,
    )


def _make_team(agent, db=None):
    return Team(
        name="Weather Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        db=db,
        telemetry=False,
        instructions=[
            "You MUST delegate all weather-related tasks to the Weather Agent.",
            "Do NOT try to answer weather questions yourself - always use the Weather Agent member.",
        ],
    )


def test_member_confirmation_pause(shared_db):
    """Team pauses when member agent tool requires confirmation."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather in Tokyo?", session_id="test_confirm_pause")

    assert response.is_paused
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_confirmation
    assert req.member_agent_name is not None
    assert req.tool_execution is not None
    assert req.tool_execution.tool_name == "get_the_weather"


def test_member_confirmation_continue(shared_db):
    """Pause -> confirm -> continue_run completes successfully."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather in Tokyo?", session_id="test_confirm_continue")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.confirm()

    result = team.continue_run(response)
    assert not result.is_paused
    assert result.content is not None


def test_member_rejection_flow(shared_db):
    """Pause -> reject with note -> continue_run processes the rejection.

    Note: After rejection, the model may either:
    1. Complete with a message acknowledging the rejection, OR
    2. Retry by calling the member agent again (which triggers another pause)

    This test verifies that the original rejection is processed correctly.
    """
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather in Tokyo?", session_id="test_reject_flow")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    original_tool_call_id = req.tool_execution.tool_call_id
    req.reject(note="User does not want weather data")

    result = team.continue_run(response)
    # The original requirement should be resolved (rejected)
    assert req.is_resolved()
    assert req.confirmation is False  # Was rejected, not confirmed
    assert result.content is not None

    # If model retried and we paused again, verify it's a NEW tool call, not the same one
    if result.is_paused and result.active_requirements:
        new_req = result.active_requirements[0]
        # Should be a different tool call (model retried)
        assert new_req.tool_execution.tool_call_id != original_tool_call_id


def test_member_confirmation_streaming(shared_db):
    """Streaming run pauses, then continues after confirmation."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    paused_event = None
    for event in team.run(
        "What is the weather in Tokyo?",
        session_id="test_confirm_stream",
        stream=True,
        stream_events=True,
    ):
        # Use isinstance to check for team's pause event (not the member agent's)
        if isinstance(event, TeamRunPausedEvent):
            paused_event = event
            break

    assert paused_event is not None
    assert paused_event.is_paused
    assert len(paused_event.requirements) >= 1

    req = paused_event.requirements[0]
    req.confirm()

    result = team.continue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None


@pytest.mark.asyncio
async def test_member_confirmation_async(shared_db):
    """Async run pauses and continues after confirmation."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = await team.arun("What is the weather in Tokyo?", session_id="test_confirm_async")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.confirm()

    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None


@pytest.mark.asyncio
async def test_member_confirmation_async_streaming(shared_db):
    """Async streaming run pauses and continues after confirmation."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    paused_event = None
    async for event in team.arun(
        "What is the weather in Tokyo?",
        session_id="test_confirm_async_stream",
        stream=True,
        stream_events=True,
    ):
        # Use isinstance to check for team's pause event (not the member agent's)
        if isinstance(event, TeamRunPausedEvent):
            paused_event = event
            break

    assert paused_event is not None
    assert paused_event.is_paused

    req = paused_event.requirements[0]
    req.confirm()

    result = await team.acontinue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None


def test_paused_event_in_stream(shared_db):
    """Streaming with events emits a TeamRunPaused event."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    found_paused_event = False
    for event in team.run(
        "What is the weather in Tokyo?", session_id="test_paused_event", stream=True, stream_events=True
    ):
        # Check for TeamRunPausedEvent using isinstance
        if isinstance(event, TeamRunPausedEvent):
            found_paused_event = True
            break

    assert found_paused_event, "TeamRunPaused event should appear in stream"


def test_unresolved_stays_paused(shared_db):
    """Calling continue_run without resolving requirements keeps team paused."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather in Tokyo?", session_id="test_unresolved")

    assert response.is_paused
    # Do NOT confirm the requirement

    result = team.continue_run(response)
    assert result.is_paused

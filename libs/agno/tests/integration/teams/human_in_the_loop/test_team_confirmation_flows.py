"""Tests for team HITL confirmation flows.

Tests that a team properly pauses when a member agent's tool requires confirmation,
propagates requirements to the team level, and resumes correctly via continue_run.
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_confirmation=True)
def get_the_weather(city: str):
    """Get the current weather for a city."""
    return f"It is currently 70 degrees and cloudy in {city}"


def _make_weather_agent(db=None):
    return Agent(
        name="WeatherAgent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=db,
        telemetry=False,
    )


def _make_team(member_agent, db=None):
    return Team(
        name="WeatherTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member_agent],
        db=db,
        telemetry=False,
        add_history_to_context=True,
    )


def test_team_member_confirmation_basic(shared_db):
    """Team pauses when member agent has a tool requiring confirmation."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.requirements is not None
    assert len(response.active_requirements) >= 1

    # Verify requirement has member context
    req = response.active_requirements[0]
    assert req.needs_confirmation
    assert req.member_agent_name == "WeatherAgent"
    assert req.member_run_id is not None
    assert req.tool_execution.tool_name == "get_the_weather"
    assert req.tool_execution.tool_args["city"] == "Tokyo"


def test_team_continue_run_with_confirmation(shared_db):
    """Team resumes correctly after confirming a member's tool."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_confirm"
    response = team.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused

    # Confirm the requirement
    req = response.active_requirements[0]
    req.confirm()

    # Continue the team run
    result = team.continue_run(response)

    assert not result.is_paused
    assert result.content is not None
    assert "70 degrees" in result.content or "cloudy" in result.content or "Tokyo" in result.content


def test_team_continue_run_with_run_id(shared_db):
    """Team can continue_run using run_id + requirements instead of run_response."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_confirm_run_id"
    response = team.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused

    # Confirm the requirement
    response.active_requirements[0].confirm()

    # Continue using run_id
    result = team.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
        session_id=session_id,
    )

    assert not result.is_paused
    assert result.content is not None


def test_team_rejection_flow(shared_db):
    """Team handles rejection of a member's tool call."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_reject"
    response = team.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused

    # Reject the requirement
    req = response.active_requirements[0]
    req.reject(note="User does not want weather data")

    # Continue the team run
    result = team.continue_run(response)

    # Run should complete (model handles the rejection)
    assert not result.is_paused


def test_team_confirmation_streaming(shared_db):
    """Team streaming pauses and resumes with confirmation."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_stream_confirm"

    # Stream the run
    paused_output = None
    for event in team.run("What is the weather in Tokyo?", session_id=session_id, stream=True, yield_run_output=True):
        from agno.run.team import TeamRunOutput

        if isinstance(event, TeamRunOutput) and event.is_paused:
            paused_output = event
            break

    assert paused_output is not None
    assert paused_output.is_paused

    # Confirm
    paused_output.active_requirements[0].confirm()

    # Continue (non-streaming)
    result = team.continue_run(paused_output)
    assert not result.is_paused


@pytest.mark.asyncio
async def test_team_confirmation_async(shared_db):
    """Async team confirmation flow."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_async_confirm"
    response = await team.arun("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused

    # Confirm
    response.active_requirements[0].confirm()

    # Continue
    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None


def test_team_paused_event_streaming(shared_db):
    """Team emits TeamRunPausedEvent when streaming with events."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_paused_event"

    events_by_type = {}
    for event in team.run(
        "What is the weather in Tokyo?",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        event_type = getattr(event, "event", None)
        if event_type:
            if event_type not in events_by_type:
                events_by_type[event_type] = []
            events_by_type[event_type].append(event)

    # Should have a paused event
    assert "TeamRunPaused" in events_by_type


@pytest.mark.asyncio
async def test_team_confirmation_async_streaming(shared_db):
    """Async streaming team confirmation flow with continue_run."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_async_stream_confirm"

    # Stream the run
    paused_output = None
    async for event in team.arun(
        "What is the weather in Tokyo?",
        session_id=session_id,
        stream=True,
        yield_run_output=True,
    ):
        from agno.run.team import TeamRunOutput

        if isinstance(event, TeamRunOutput) and event.is_paused:
            paused_output = event

    assert paused_output is not None
    assert paused_output.is_paused

    # Confirm
    paused_output.active_requirements[0].confirm()

    # Continue (non-streaming)
    result = await team.acontinue_run(paused_output)
    assert not result.is_paused
    assert result.content is not None


def test_team_continue_run_unresolved_stays_paused(shared_db):
    """Team stays paused when continue_run is called without resolving requirements."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_unresolved"
    response = team.run("What is the weather in Tokyo?", session_id=session_id)

    assert response.is_paused

    # Do NOT resolve the requirement -- continue immediately
    result = team.continue_run(response)

    # Should still be paused since the requirement was not resolved
    assert result.is_paused


def test_team_chained_hitl_multi_round(shared_db):
    """Team handles multiple pause-resume rounds in the same session.

    Round 1: Ask weather for Tokyo -> pause -> confirm -> complete
    Round 2: Ask weather for Paris (same session) -> pause -> confirm -> complete
    """
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_chained"

    # Round 1: first query triggers pause
    response = team.run("What is the weather in Tokyo?", session_id=session_id)
    assert response.is_paused
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.confirm()

    result = team.continue_run(response)
    assert not result.is_paused
    assert result.content is not None

    # Round 2: second query in the same session triggers another pause
    response2 = team.run("Now what is the weather in Paris?", session_id=session_id)
    assert response2.is_paused
    assert len(response2.active_requirements) >= 1

    req2 = response2.active_requirements[0]
    assert req2.needs_confirmation
    req2.confirm()

    result2 = team.continue_run(response2)
    assert not result2.is_paused
    assert result2.content is not None

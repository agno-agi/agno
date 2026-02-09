"""Integration tests for team HITL user input flows.

Tests sync/async/streaming flows where member agent tools require user input.
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_user_input=True, user_input_fields=["city"])
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


def _make_agent(db=None):
    return Agent(
        name="Weather Agent",
        role="Provides weather information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_the_weather],
        db=db,
        telemetry=False,
    )


def _make_team(agent, db=None):
    return Team(
        name="Weather Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent],
        db=db,
        telemetry=False,
    )


def test_member_user_input_pause(shared_db):
    """Team pauses when member agent tool requires user input."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("Get me the weather", session_id="test_user_input_pause")

    assert response.is_paused
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_user_input
    assert req.user_input_schema is not None
    field_names = [f.name for f in req.user_input_schema]
    assert "city" in field_names


def test_member_user_input_continue(shared_db):
    """Pause -> provide user input -> continue_run completes."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("Get me the weather", session_id="test_user_input_continue")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_user_input

    req.provide_user_input({"city": "Tokyo"})

    result = team.continue_run(response)
    assert not result.is_paused
    assert result.content is not None


@pytest.mark.asyncio
async def test_member_user_input_async(shared_db):
    """Async user input flow."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = await team.arun("Get me the weather", session_id="test_user_input_async")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_user_input

    req.provide_user_input({"city": "Paris"})

    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None


def test_member_user_input_streaming(shared_db):
    """Streaming user input flow."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    paused_output = None
    for event in team.run("Get me the weather", session_id="test_user_input_stream", stream=True, stream_events=True):
        if hasattr(event, "is_paused") and event.is_paused:
            paused_output = event
            break

    assert paused_output is not None
    assert paused_output.is_paused

    req = paused_output.requirements[0]
    assert req.needs_user_input

    req.provide_user_input({"city": "London"})

    result = team.continue_run(paused_output)
    assert not result.is_paused
    assert result.content is not None

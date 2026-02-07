"""Tests for team HITL user input flows.

Tests that a team properly handles member agents with tools that require
user input before execution.
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_user_input=True, user_input_fields=["city"])
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


def test_team_user_input_basic(shared_db):
    """Team pauses when member has a tool requiring user input."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run("What is the weather?")

    assert response.is_paused
    assert response.requirements is not None
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_user_input
    assert req.member_agent_name == "WeatherAgent"

    # Verify user input schema
    input_schema = req.user_input_schema
    assert input_schema is not None
    assert len(input_schema) >= 1
    assert input_schema[0].name == "city"


def test_team_continue_run_user_input(shared_db):
    """Team resumes after providing user input."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_user_input"
    response = team.run("What is the weather?", session_id=session_id)

    assert response.is_paused

    # Provide user input
    req = response.active_requirements[0]
    req.provide_user_input({"city": "Tokyo"})

    # Continue the run
    result = team.continue_run(response)

    assert not result.is_paused
    assert result.content is not None
    assert "70 degrees" in result.content or "cloudy" in result.content or "Tokyo" in result.content


def test_team_user_input_with_run_id(shared_db):
    """Team user input using run_id + requirements."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_user_input_run_id"
    response = team.run("What is the weather?", session_id=session_id)

    assert response.is_paused

    # Provide user input
    response.active_requirements[0].provide_user_input({"city": "Tokyo"})

    # Continue using run_id
    result = team.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
        session_id=session_id,
    )

    assert not result.is_paused


@pytest.mark.asyncio
async def test_team_user_input_async(shared_db):
    """Async team user input flow."""
    agent = _make_weather_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_user_input_async"
    response = await team.arun("What is the weather?", session_id=session_id)

    assert response.is_paused

    # Provide user input
    response.active_requirements[0].provide_user_input({"city": "Tokyo"})

    # Continue
    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None

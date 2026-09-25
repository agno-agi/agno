"""Integration tests for continuing a paused team run with background=True and stream=True.

A background continue persists the team run as PENDING/RUNNING before its messages are
rebuilt, so the continued run must not be read back as its own history. Covers both a
tool on the team itself and a tool on a member agent. Chat Completions rejects a
duplicated, unanswered tool call, so the bug makes the continue end in ERROR.
"""

import asyncio
import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(requires_confirmation=True)
def approve_deployment(app_name: str, environment: str) -> str:
    """Approve a deployment to the specified environment.

    Args:
        app_name: Name of the application to deploy.
        environment: Target environment (staging, production).
    """
    return f"Deployed {app_name} to {environment} successfully"


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get weather for.
    """
    return f"It is currently 70 degrees and cloudy in {city}"


def _make_team_tool_team(db, **kwargs) -> Team:
    helper = Agent(
        name="Helper Agent",
        role="Assists with general questions",
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
    )
    return Team(
        name="Deploy Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[helper],
        tools=[approve_deployment],
        db=db,
        add_history_to_context=True,
        telemetry=False,
        **kwargs,
        instructions=[
            "You MUST use the approve_deployment tool when asked to deploy an application.",
            "Do NOT respond without using the tool - always call approve_deployment first.",
        ],
    )


def _make_member_tool_team(db) -> Team:
    weather_agent = Agent(
        name="Weather Agent",
        role="Provides weather information. Use the get_the_weather tool to get weather data.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        db=db,
        telemetry=False,
    )
    return Team(
        name="Weather Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[weather_agent],
        db=db,
        add_history_to_context=True,
        telemetry=False,
        instructions=[
            "You MUST delegate all weather-related tasks to the Weather Agent.",
            "Do NOT try to answer weather questions yourself - always use the Weather Agent member.",
        ],
    )


async def _wait_for_terminal_run(team: Team, run_id: str, session_id: str, timeout: float = 60.0) -> TeamRunOutput:
    """Background runs finish on a detached task, so poll the database for a settled status."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        run = await team.aget_run_output(run_id=run_id, session_id=session_id)
        if run is not None and run.status not in (RunStatus.pending, RunStatus.running):
            return run  # type: ignore[return-value]
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"Run {run_id} did not settle; last status: {run.status if run else None}")
        await asyncio.sleep(0.1)


async def _start_background_stream(team: Team, message: str, session_id: str) -> TeamRunOutput:
    async for _ in team.arun(message, session_id=session_id, stream=True, background=True):
        pass
    last = team.get_last_run_output(session_id=session_id)
    assert last is not None and last.run_id is not None
    return await _wait_for_terminal_run(team, last.run_id, session_id)


async def _continue_background_stream(team: Team, run: TeamRunOutput) -> TeamRunOutput:
    assert run.run_id is not None and run.session_id is not None
    for requirement in run.active_requirements:
        requirement.confirm()
    async for _ in team.acontinue_run(
        run_id=run.run_id,
        session_id=run.session_id,
        requirements=run.requirements,
        stream=True,
        background=True,
    ):
        pass
    return await _wait_for_terminal_run(team, run.run_id, run.session_id)


@pytest.mark.asyncio
async def test_team_tool_background_stream_continue(shared_db):
    team = _make_team_tool_team(shared_db)
    session_id = "team-tool-bg-stream"

    paused = await _start_background_stream(team, "Deploy myapp to production", session_id)
    assert paused.status == RunStatus.paused, f"expected a pause, got {paused.status}: {paused.content}"

    completed = await _continue_background_stream(team, paused)

    assert completed.status == RunStatus.completed, f"continue ended {completed.status}: {completed.content}"


@pytest.mark.asyncio
async def test_member_tool_background_stream_continue(shared_db):
    """Member-level HITL resumes through the member agent; covered here so it stays working."""
    team = _make_member_tool_team(shared_db)
    session_id = "member-tool-bg-stream"

    paused = await _start_background_stream(team, "What is the weather in Tokyo?", session_id)
    assert paused.status == RunStatus.paused, f"expected a pause, got {paused.status}: {paused.content}"

    completed = await _continue_background_stream(team, paused)

    assert completed.status == RunStatus.completed, f"continue ended {completed.status}: {completed.content}"


@pytest.mark.asyncio
async def test_team_background_stream_continue_keeps_prior_history(shared_db):
    """Excluding the continued run must not drop genuinely earlier team turns from history."""
    team = _make_team_tool_team(
        shared_db,
        additional_context="IMPORTANT: Always address the user by their name in every response.",
    )
    session_id = "team-bg-stream-history"

    first = await _start_background_stream(team, "Hi, my name is Alice.", session_id)
    assert first.status == RunStatus.completed

    paused = await _start_background_stream(team, "Deploy myapp to production", session_id)
    assert paused.status == RunStatus.paused

    completed = await _continue_background_stream(team, paused)
    assert completed.status == RunStatus.completed, f"continue ended {completed.status}: {completed.content}"

    # The name only reaches the continued request through history from the first run
    assert "alice" in (completed.content or "").lower(), f"prior history missing: {completed.content}"

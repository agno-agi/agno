"""Integration tests for team-level tool HITL.

Tests HITL for tools provided directly to the Team (vs. member agent tools).
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
def approve_deployment(app_name: str, environment: str) -> str:
    """Approve a deployment to the specified environment.

    Args:
        app_name: Name of the application to deploy.
        environment: Target environment (staging, production).
    """
    return f"Deployed {app_name} to {environment} successfully"


def _make_team(db=None):
    """Create a team with the HITL tool on the team itself (no member agents with tools)."""
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
        telemetry=False,
        instructions=[
            "You MUST use the approve_deployment tool when asked to deploy an application.",
            "Do NOT respond without using the tool - always call approve_deployment first.",
        ],
    )


def test_team_tool_confirmation_pause(shared_db):
    """Team pauses when a team-level tool requires confirmation."""
    team = _make_team(db=shared_db)

    response = team.run("Deploy myapp to production", session_id="test_team_tool_pause")

    assert response.is_paused
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_confirmation
    assert req.tool_execution is not None
    assert req.tool_execution.tool_name == "approve_deployment"
    # Team-level tools should NOT have member context
    assert req.member_agent_id is None


def test_team_tool_confirmation_continue(shared_db):
    """Team-level tool: pause -> confirm -> continue completes."""
    team = _make_team(db=shared_db)

    response = team.run("Deploy myapp to production", session_id="test_team_tool_continue")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.confirm()

    result = team.continue_run(response)
    assert not result.is_paused
    assert result.content is not None


@pytest.mark.asyncio
async def test_team_tool_confirmation_async(shared_db):
    """Async team-level tool confirmation flow."""
    team = _make_team(db=shared_db)

    response = await team.arun("Deploy myapp to staging", session_id="test_team_tool_async")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.confirm()

    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None


def test_team_tool_confirmation_streaming(shared_db):
    """Streaming team-level tool confirmation flow."""
    team = _make_team(db=shared_db)

    paused_event = None
    for event in team.run(
        "Deploy myapp to staging",
        session_id="test_team_tool_stream",
        stream=True,
        stream_events=True,
    ):
        # Use isinstance to check for team's pause event
        if isinstance(event, TeamRunPausedEvent):
            paused_event = event
            break

    assert paused_event is not None
    assert paused_event.is_paused

    req = paused_event.active_requirements[0]
    assert req.needs_confirmation
    assert req.member_agent_id is None
    req.confirm()

    result = team.continue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None


@pytest.mark.asyncio
async def test_team_tool_confirmation_async_streaming(shared_db):
    """Async streaming team-level tool confirmation flow."""
    team = _make_team(db=shared_db)

    paused_event = None
    async for event in team.arun(
        "Deploy myapp to staging",
        session_id="test_team_tool_async_stream",
        stream=True,
        stream_events=True,
    ):
        # Use isinstance to check for team's pause event
        if isinstance(event, TeamRunPausedEvent):
            paused_event = event
            break

    assert paused_event is not None
    assert paused_event.is_paused

    req = paused_event.active_requirements[0]
    assert req.needs_confirmation
    assert req.member_agent_id is None
    req.confirm()

    result = await team.acontinue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None


def test_team_tool_rejection(shared_db):
    """Team-level tool: reject -> continue handles gracefully."""
    team = _make_team(db=shared_db)

    response = team.run("Deploy myapp to production", session_id="test_team_tool_reject")

    assert response.is_paused
    req = response.active_requirements[0]
    assert req.needs_confirmation
    req.reject(note="Deployment not approved by ops team")

    result = team.continue_run(response)
    assert not result.is_paused
    assert result.content is not None

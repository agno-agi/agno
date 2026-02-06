"""Tests for team HITL external execution flows.

Tests that a team properly handles member agents with tools that require
external execution (results provided by the caller, not the agent).
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.decorator import tool


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str):
    """Send an email externally."""
    pass


def _make_email_agent(db=None):
    return Agent(
        name="EmailAgent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=db,
        telemetry=False,
    )


def _make_team(member_agent, db=None):
    return Team(
        name="EmailTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member_agent],
        db=db,
        telemetry=False,
        add_history_to_context=True,
    )


def test_team_external_execution_basic(shared_db):
    """Team pauses when member has a tool requiring external execution."""
    agent = _make_email_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    response = team.run(
        "Send an email to john@doe.com with subject 'Hello' and body 'Hi there'",
    )

    assert response.is_paused
    assert response.requirements is not None
    assert len(response.active_requirements) >= 1

    req = response.active_requirements[0]
    assert req.needs_external_execution
    assert req.member_agent_name == "EmailAgent"
    assert req.tool_execution.tool_name == "send_email"


def test_team_continue_run_external_execution(shared_db):
    """Team resumes after providing external execution result."""
    agent = _make_email_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_ext_exec"
    response = team.run(
        "Send an email to john@doe.com with subject 'Hello' and body 'Hi there'",
        session_id=session_id,
    )

    assert response.is_paused

    # Provide external result
    req = response.active_requirements[0]
    req.set_external_execution_result("Email sent successfully to john@doe.com")

    # Continue the run
    result = team.continue_run(response)

    assert not result.is_paused
    assert result.content is not None


def test_team_external_execution_with_run_id(shared_db):
    """Team external execution using run_id + requirements."""
    agent = _make_email_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_ext_exec_run_id"
    response = team.run(
        "Send an email to john@doe.com with subject 'Hello' and body 'Hi there'",
        session_id=session_id,
    )

    assert response.is_paused

    # Provide external result
    response.active_requirements[0].set_external_execution_result("Email sent successfully")

    # Continue using run_id
    result = team.continue_run(
        run_id=response.run_id,
        requirements=response.requirements,
        session_id=session_id,
    )

    assert not result.is_paused


@pytest.mark.asyncio
async def test_team_external_execution_async(shared_db):
    """Async team external execution flow."""
    agent = _make_email_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    session_id = "test_team_ext_exec_async"
    response = await team.arun(
        "Send an email to john@doe.com with subject 'Hello' and body 'Hi there'",
        session_id=session_id,
    )

    assert response.is_paused

    # Provide external result
    response.active_requirements[0].set_external_execution_result("Email sent successfully")

    # Continue
    result = await team.acontinue_run(response)
    assert not result.is_paused
    assert result.content is not None

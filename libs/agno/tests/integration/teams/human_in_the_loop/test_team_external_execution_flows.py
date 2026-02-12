"""Integration tests for team HITL external execution flows.

Tests sync/async/streaming flows where member agent tools are executed externally.
"""

import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools.decorator import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient.

    Args:
        to: The recipient email address.
        subject: The email subject.
        body: The email body.
    """
    return f"Email sent to {to}"


def _make_agent(db=None):
    return Agent(
        name="Email Agent",
        role="Handles email operations. Use the send_email tool to send emails.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=db,
        telemetry=False,
    )


def _make_team(agent, db=None):
    return Team(
        name="Comms Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        db=db,
        telemetry=False,
        instructions=[
            "You MUST delegate all email-related tasks to the Email Agent.",
            "Do NOT try to handle email tasks yourself - always use the Email Agent member.",
        ],
    )


# def test_member_external_execution_pause(shared_db):
#     """Team pauses when member agent tool requires external execution."""
#     agent = _make_agent(db=shared_db)
#     team = _make_team(agent, db=shared_db)

#     response = team.run(
#         "Send an email to john@example.com with subject 'Hello' and body 'Hi there'",
#         session_id="test_ext_exec_pause",
#     )

#     assert response.is_paused
#     assert len(response.active_requirements) >= 1

#     req = response.active_requirements[0]
#     assert req.needs_external_execution
#     assert req.tool_execution is not None
#     assert req.tool_execution.tool_name == "send_email"


# def test_member_external_execution_continue(shared_db):
#     """Pause -> provide external result -> continue_run completes."""
#     agent = _make_agent(db=shared_db)
#     team = _make_team(agent, db=shared_db)

#     response = team.run(
#         "Send an email to john@example.com with subject 'Hello' and body 'Hi there'",
#         session_id="test_ext_exec_continue",
#     )

#     assert response.is_paused
#     req = response.active_requirements[0]
#     assert req.needs_external_execution

#     req.set_external_execution_result("Email sent successfully to john@example.com")

#     result = team.continue_run(response)
#     assert not result.is_paused
#     assert result.content is not None


# @pytest.mark.asyncio
# async def test_member_external_execution_async(shared_db):
#     """Async external execution flow."""
#     agent = _make_agent(db=shared_db)
#     team = _make_team(agent, db=shared_db)

#     response = await team.arun(
#         "Send an email to john@example.com with subject 'Hello' and body 'Hi there'",
#         session_id="test_ext_exec_async",
#     )

#     assert response.is_paused
#     req = response.active_requirements[0]
#     assert req.needs_external_execution

#     req.set_external_execution_result("Email sent successfully to john@example.com")

#     result = await team.acontinue_run(response)
#     assert not result.is_paused
#     assert result.content is not None


@pytest.mark.asyncio
async def test_member_external_execution_async_streaming(shared_db):
    """Async streaming external execution flow."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    paused_event = None
    async for event in team.arun(
        "Send an email to john@example.com with subject 'Hello' and body 'Hi there'",
        session_id="test_ext_exec_async_stream",
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
    assert req.needs_external_execution

    req.set_external_execution_result("Email sent successfully to john@example.com")

    result = await team.acontinue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None


def test_member_external_execution_streaming(shared_db):
    """Streaming external execution flow."""
    agent = _make_agent(db=shared_db)
    team = _make_team(agent, db=shared_db)

    paused_event = None
    for event in team.run(
        "Send an email to john@example.com with subject 'Hello' and body 'Hi there'",
        session_id="test_ext_exec_stream",
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
    assert req.needs_external_execution

    req.set_external_execution_result("Email sent successfully to john@example.com")

    result = team.continue_run(
        run_id=paused_event.run_id,
        session_id=paused_event.session_id,
        requirements=paused_event.requirements,
    )
    assert not result.is_paused
    assert result.content is not None

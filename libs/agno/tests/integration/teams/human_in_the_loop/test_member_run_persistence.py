"""Integration tests for member run persistence during team HITL continue.

Verifies that after a member agent's HITL requirement is resolved and the team
continues, the member's completed RunOutput is persisted to the team session
via session.upsert_run(). This is critical for:
- Session reload showing correct member state
- Multi-round HITL in the same session
- API flows where the FE reloads the session after continue
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
def deploy_to_env(service: str, environment: str) -> str:
    """Deploy a service to an environment.

    Args:
        service: Name of the service to deploy.
        environment: Target environment (staging, production).
    """
    return f"Deployed {service} to {environment}"


def _make_agent(db=None):
    return Agent(
        name="Deploy Agent",
        role="Handles deployments. Always use the deploy_to_env tool.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[deploy_to_env],
        db=db,
        telemetry=False,
    )


def _make_team(agent, db=None):
    return Team(
        name="DevOps Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        db=db,
        telemetry=False,
        instructions=[
            "You MUST delegate all deployment tasks to the Deploy Agent.",
            "Do NOT try to deploy yourself - always use the Deploy Agent member.",
        ],
    )


# ===========================================================================
# Sync tests
# ===========================================================================


class TestMemberRunPersistenceSync:
    """Sync: member run is persisted after continue_run."""

    def test_member_run_persisted_after_continue(self, shared_db):
        """After confirm + continue, the member's run should be in the session."""
        agent = _make_agent(db=shared_db)
        team = _make_team(agent, db=shared_db)

        session_id = "test_member_persist_sync"
        response = team.run("Deploy auth service to staging", session_id=session_id)

        assert response.is_paused, "Team should pause for member confirmation"
        req = response.active_requirements[0]
        req.confirm()

        result = team.continue_run(response)
        assert not result.is_paused
        assert result.content is not None

        # Reload session and verify member run is persisted
        session = team.get_session(session_id=session_id)
        assert session is not None
        assert session.runs is not None
        assert len(session.runs) >= 1

        # Find the member's run (has agent_id, not team_id)
        member_runs = [r for r in session.runs if hasattr(r, "agent_id") and getattr(r, "agent_id", None)]
        assert len(member_runs) >= 1, "Member agent's run should be persisted in the session"

        member_run = member_runs[0]
        assert member_run.content is not None, "Member run should have content"

    def test_member_run_persisted_after_streaming_continue(self, shared_db):
        """After streaming confirm + continue, the member's run should be in the session."""
        agent = _make_agent(db=shared_db)
        team = _make_team(agent, db=shared_db)

        session_id = "test_member_persist_stream_sync"

        paused_event = None
        for event in team.run("Deploy payments to production", session_id=session_id, stream=True):
            if isinstance(event, TeamRunPausedEvent):
                paused_event = event
                break

        assert paused_event is not None, "Team should pause"

        for req in paused_event.active_requirements:
            req.confirm()

        # Continue with streaming
        for event in team.continue_run(
            run_id=paused_event.run_id,
            session_id=paused_event.session_id,
            requirements=paused_event.requirements,
            stream=True,
        ):
            pass  # consume stream

        # Reload and verify
        session = team.get_session(session_id=session_id)
        assert session is not None
        member_runs = [r for r in (session.runs or []) if hasattr(r, "agent_id") and getattr(r, "agent_id", None)]
        assert len(member_runs) >= 1, "Member run should be persisted after streaming continue"

    def test_two_hitl_runs_same_session(self, shared_db):
        """Two HITL runs in same session should both persist member runs."""
        agent = _make_agent(db=shared_db)
        team = _make_team(agent, db=shared_db)

        session_id = "test_two_runs_persist"

        # Run 1
        response1 = team.run("Deploy auth to staging", session_id=session_id)
        assert response1.is_paused
        response1.active_requirements[0].confirm()
        result1 = team.continue_run(response1)
        assert not result1.is_paused

        # Run 2 — same session
        response2 = team.run("Deploy payments to production", session_id=session_id)
        assert response2.is_paused
        response2.active_requirements[0].confirm()
        result2 = team.continue_run(response2)
        assert not result2.is_paused

        # Reload and verify both member runs are persisted
        session = team.get_session(session_id=session_id)
        assert session is not None
        member_runs = [r for r in (session.runs or []) if hasattr(r, "agent_id") and getattr(r, "agent_id", None)]
        assert len(member_runs) >= 2, f"Both member runs should be persisted, found {len(member_runs)}"


# ===========================================================================
# Async tests
# ===========================================================================


class TestMemberRunPersistenceAsync:
    """Async: member run is persisted after acontinue_run."""

    @pytest.mark.asyncio
    async def test_member_run_persisted_after_async_continue(self, shared_db):
        agent = _make_agent(db=shared_db)
        team = _make_team(agent, db=shared_db)

        session_id = "test_member_persist_async"
        response = await team.arun("Deploy auth service to staging", session_id=session_id)

        assert response.is_paused
        req = response.active_requirements[0]
        req.confirm()

        result = await team.acontinue_run(response)
        assert not result.is_paused
        assert result.content is not None

        # Reload and verify
        session = team.get_session(session_id=session_id)
        assert session is not None
        member_runs = [r for r in (session.runs or []) if hasattr(r, "agent_id") and getattr(r, "agent_id", None)]
        assert len(member_runs) >= 1, "Member run should be persisted after async continue"

    @pytest.mark.asyncio
    async def test_member_run_persisted_after_async_streaming_continue(self, shared_db):
        agent = _make_agent(db=shared_db)
        team = _make_team(agent, db=shared_db)

        session_id = "test_member_persist_async_stream"

        paused_event = None
        async for event in team.arun("Deploy payments to production", session_id=session_id, stream=True):
            if isinstance(event, TeamRunPausedEvent):
                paused_event = event
                break

        assert paused_event is not None

        for req in paused_event.active_requirements:
            req.confirm()

        async for event in team.acontinue_run(
            run_id=paused_event.run_id,
            session_id=paused_event.session_id,
            requirements=paused_event.requirements,
            stream=True,
        ):
            pass

        session = team.get_session(session_id=session_id)
        assert session is not None
        member_runs = [r for r in (session.runs or []) if hasattr(r, "agent_id") and getattr(r, "agent_id", None)]
        assert len(member_runs) >= 1, "Member run should be persisted after async streaming continue"

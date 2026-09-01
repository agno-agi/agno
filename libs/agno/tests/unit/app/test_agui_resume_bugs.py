"""
Reproduce bugs reported in PR #8565 review:
1. resume_paused_run picks oldest paused run, not newest
2. resolve_requirements_from_tool_messages crashes on non-external-execution requirements
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.resume import resolve_requirements_from_tool_messages, resume_paused_run
from agno.run.agent import RunOutput
from agno.run.base import RunContext, RunStatus
from agno.run.requirement import RunRequirement
from agno.session.agent import AgentSession


class FakeToolMessage:
    def __init__(self, tool_call_id: str, content: str, error: str = None):
        self.tool_call_id = tool_call_id
        self.content = content
        self.error = error


def _make_paused_run(run_id: str, tool_call_ids: list[str]) -> RunOutput:
    """Create a paused run with external execution requirements."""
    return RunOutput(
        run_id=run_id,
        session_id="test-session",
        status=RunStatus.paused,
        requirements=[
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id=tc_id,
                    tool_name=f"tool_{tc_id}",
                    tool_args={},
                    external_execution_required=True,
                )
            )
            for tc_id in tool_call_ids
        ],
    )


class TestBug1_OldestPausedRunPicked:
    """
    Bug: resume_paused_run picks the oldest paused run, not the newest.

    Scenario:
    1. run1 starts and pauses (tool_call_id: call_old)
    2. User ignores, sends new message
    3. run2 starts and pauses (tool_call_id: call_new)
    4. User executes run2's tools and sends ToolMessages with call_new
    5. resume_paused_run should find run2, not run1
    """

    @pytest.mark.asyncio
    async def test_multiple_paused_runs_picks_wrong_one(self):
        """BUG REPRODUCTION: Multiple paused runs, newest should be picked."""
        from agno.agent import Agent

        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()

        # Session has TWO paused runs - old one first, new one second
        session = AgentSession(session_id="test-session")
        old_run = _make_paused_run("old-run", ["call_old_1", "call_old_2"])
        new_run = _make_paused_run("new-run", ["call_new_1", "call_new_2"])
        session.runs = [old_run, new_run]  # append order: oldest first

        entity.aget_session = AsyncMock(return_value=session)
        entity.acontinue_run = MagicMock(return_value=AsyncMock())

        # Frontend sends results for the NEW run's tools
        tool_messages = [
            FakeToolMessage("call_new_1", "result 1"),
            FakeToolMessage("call_new_2", "result 2"),
        ]

        run_context = RunContext(run_id="frontend-new-run-id", session_id="test-session")

        await resume_paused_run(
            entity=entity,
            session_id="test-session",
            tool_messages=tool_messages,
            run_context=run_context,
            run_kwargs={},
        )

        # EXPECTED: Should resume new-run since those are the matching tool_call_ids
        # BUG: Currently picks old-run (first in list)
        call_kwargs = entity.acontinue_run.call_args.kwargs

        # This assertion will FAIL if the bug exists
        assert call_kwargs["run_id"] == "new-run", (
            f"Expected to resume 'new-run' but got '{call_kwargs['run_id']}'. "
            "Bug: picks oldest paused run instead of matching one."
        )


class TestBug2_CrashOnNonExternalRequirement:
    """
    Bug: resolve_requirements_from_tool_messages crashes if a matched requirement
    isn't awaiting external execution.

    Scenario:
    1. Requirement exists with tool_call_id but is already resolved
    2. Frontend retries and sends the same ToolMessage again
    3. set_external_execution_result() raises because needs_external_execution is False
    """

    def test_already_resolved_requirement_crashes(self):
        """BUG REPRODUCTION: Applying result to already-resolved requirement should not crash."""
        # Create a requirement that WAS external but is now resolved
        req = RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_1",
                tool_name="change_background",
                tool_args={"color": "blue"},
                external_execution_required=True,
            )
        )
        # Resolve it (simulates first successful apply)
        req.set_external_execution_result("Already done")

        # Now it's resolved: needs_external_execution returns False
        assert req.needs_external_execution is False

        # Frontend retries (network glitch, duplicate request)
        tool_messages = [FakeToolMessage("call_1", "Duplicate result")]

        # BUG: This should NOT crash, but currently it will
        # because set_external_execution_result raises on resolved requirements
        try:
            resolve_requirements_from_tool_messages([req], tool_messages)
            # If we get here without crash, bug is fixed or doesn't exist
        except ValueError as e:
            pytest.fail(
                f"Crashed on already-resolved requirement: {e}. "
                "Bug: should skip non-external requirements instead of crashing."
            )

    def test_confirmation_requirement_with_unmatched_id_unchanged(self):
        """Confirmation requirements with non-matching tool_call_ids stay unchanged."""
        req = RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_confirmation",
                tool_name="delete_file",
                tool_args={"path": "/tmp/foo"},
                requires_confirmation=True,
            )
        )

        # Different tool_call_id, should not match
        tool_messages = [FakeToolMessage("call_other", "some result")]

        result = resolve_requirements_from_tool_messages([req], tool_messages)

        # Unmatched requirement stays unresolved
        assert result[0].is_resolved() is False
        assert result[0].tool_execution.confirmed is None


class TestBug2_Variant_MixedRequirements:
    """
    More realistic scenario: paused run has both external and confirmation requirements.
    Both pause types are now handled by resolve_requirements_from_tool_messages.
    """

    def test_mixed_requirements_all_processed_correctly(self):
        """All pause types are processed by resolve_requirements_from_tool_messages."""
        external_req = RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_ext",
                tool_name="change_background",
                external_execution_required=True,
            )
        )
        confirmation_req = RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id="call_confirm",
                tool_name="delete_file",
                requires_confirmation=True,
            )
        )

        tool_messages = [
            FakeToolMessage("call_ext", "Background changed"),
            FakeToolMessage("call_confirm", '{"accepted": true}'),
        ]

        result = resolve_requirements_from_tool_messages([external_req, confirmation_req], tool_messages)

        # External execution: result set directly
        assert result[0].is_resolved()
        assert result[0].external_execution_result == "Background changed"

        # Confirmation: confirmed flag set
        assert result[1].is_resolved()
        assert result[1].tool_execution.confirmed is True

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent
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


def _make_paused_run(run_id: str = "paused-run-123") -> RunOutput:
    return RunOutput(
        run_id=run_id,
        session_id="test-session",
        status=RunStatus.paused,
        requirements=[
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id="call_1",
                    tool_name="change_background",
                    tool_args={"color": "blue"},
                    external_execution_required=True,
                )
            )
        ],
    )


def _make_session_with_paused_run() -> AgentSession:
    session = AgentSession(session_id="test-session")
    session.runs = [_make_paused_run()]
    return session


class TestNothingToResume:
    """A trailing tool result no paused run is waiting on is not a resume.

    Each case here says the same thing to the caller: this session holds no
    paused run these results answer, so the router owes them a new turn rather
    than a failed one. A client mints tool call ids the backend never emitted
    (an interactive surface reports a click that way), so this is ordinary
    traffic, not a broken resume.
    """

    async def _resume(self, entity, session_id: str):
        return await resume_paused_run(
            entity=entity,
            session_id=session_id,
            tool_messages=[FakeToolMessage("call_1", "result")],
            run_context=RunContext(run_id="new-run", session_id=session_id),
            run_kwargs={},
        )

    @pytest.mark.asyncio
    async def test_no_db_cannot_hold_a_paused_run(self):
        # spec=Agent needed for isinstance() check in resume_paused_run
        entity = MagicMock(spec=Agent)
        entity.db = None

        assert await self._resume(entity, "test-session") is None

    @pytest.mark.asyncio
    async def test_a_session_that_is_gone_holds_no_paused_run(self):
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        entity.aget_session = AsyncMock(return_value=None)

        assert await self._resume(entity, "missing-session") is None

    @pytest.mark.asyncio
    async def test_a_session_of_completed_runs_holds_no_paused_run(self):
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        session = AgentSession(session_id="test-session")
        session.runs = [RunOutput(run_id="completed-run", status=RunStatus.completed)]
        entity.aget_session = AsyncMock(return_value=session)

        assert await self._resume(entity, "test-session") is None

    @pytest.mark.asyncio
    async def test_a_paused_run_with_no_requirements_waits_on_nothing(self):
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        session = AgentSession(session_id="test-session")
        session.runs = [RunOutput(run_id="paused-run", status=RunStatus.paused, requirements=None)]
        entity.aget_session = AsyncMock(return_value=session)

        assert await self._resume(entity, "test-session") is None

    @pytest.mark.asyncio
    async def test_an_unmatched_tool_call_id_leaves_a_paused_run_alone(self):
        """The paused run waits on call_1; these results answer something else."""
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        entity.aget_session = AsyncMock(return_value=_make_session_with_paused_run())
        entity.acontinue_run = MagicMock(return_value=AsyncMock())

        resumed = await resume_paused_run(
            entity=entity,
            session_id="test-session",
            tool_messages=[FakeToolMessage("767065f4-7cc3-42d4", 'User performed action "bookHotel"')],
            run_context=RunContext(run_id="new-run", session_id="test-session"),
            run_kwargs={},
        )

        assert resumed is None
        entity.acontinue_run.assert_not_called()


class TestResumePausedRunHappyPath:
    @pytest.mark.asyncio
    async def test_calls_acontinue_run_with_correct_args(self):
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        entity.aget_session = AsyncMock(return_value=_make_session_with_paused_run())
        entity.acontinue_run = MagicMock(return_value=AsyncMock())

        run_context = RunContext(run_id="new-run-from-frontend", session_id="test-session")

        await resume_paused_run(
            entity=entity,
            session_id="test-session",
            tool_messages=[FakeToolMessage("call_1", "Background changed")],
            run_context=run_context,
            run_kwargs={"extra_kwarg": "value"},
        )

        entity.acontinue_run.assert_called_once()
        call_kwargs = entity.acontinue_run.call_args.kwargs

        assert call_kwargs["run_id"] == "paused-run-123"
        assert call_kwargs["session_id"] == "test-session"
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True
        assert call_kwargs["extra_kwarg"] == "value"
        assert run_context.run_id == "paused-run-123"

    @pytest.mark.asyncio
    async def test_applies_tool_results_to_requirements(self):
        entity = MagicMock(spec=Agent)
        entity.db = MagicMock()
        entity.aget_session = AsyncMock(return_value=_make_session_with_paused_run())
        entity.acontinue_run = MagicMock(return_value=AsyncMock())

        await resume_paused_run(
            entity=entity,
            session_id="test-session",
            tool_messages=[FakeToolMessage("call_1", "Tool executed successfully")],
            run_context=RunContext(run_id="new-run", session_id="test-session"),
            run_kwargs={},
        )

        call_kwargs = entity.acontinue_run.call_args.kwargs
        requirements = call_kwargs["requirements"]

        assert len(requirements) == 1
        assert requirements[0].external_execution_result == "Tool executed successfully"
        assert requirements[0].tool_execution.result == "Tool executed successfully"


class TestApplyToolResultsEdgeCases:
    def test_skips_requirement_without_tool_execution(self):
        requirements = [
            RunRequirement(tool_execution=None),
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id="call_1",
                    tool_name="my_tool",
                    external_execution_required=True,
                )
            ),
        ]
        tool_messages = [FakeToolMessage("call_1", "result")]

        result = resolve_requirements_from_tool_messages(requirements, tool_messages)

        assert result[0].tool_execution is None
        assert result[1].tool_execution.result == "result"

    def test_skips_requirement_without_tool_call_id(self):
        requirements = [
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id=None,
                    tool_name="no_id_tool",
                    external_execution_required=True,
                )
            ),
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id="call_1",
                    tool_name="has_id_tool",
                    external_execution_required=True,
                )
            ),
        ]
        tool_messages = [FakeToolMessage("call_1", "result")]

        result = resolve_requirements_from_tool_messages(requirements, tool_messages)

        assert result[0].tool_execution.result is None
        assert result[1].tool_execution.result == "result"

"""
Unit tests for issue #7185.

When a Step's Agent/Team executor fails mid-stream, the executor yields a
terminal error event (RunErrorEvent / TeamRunErrorEvent) and never yields a
(Team)RunOutput. Previously the streaming Step paths left
``active_executor_run_response`` as ``None`` and silently emitted an empty,
*successful* StepOutput -- masking the executor's real error. The non-streaming
paths already surfaced the failure because the executor returns a RunOutput with
``status=error``.

These tests assert that ALL four Step execution paths (sync/async x
stream/non-stream) surface the executor failure as ``success=False`` with the
underlying error, for both Team and Agent executors.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.workflow import WorkflowCompletedEvent
from agno.team import Team
from agno.workflow import Workflow
from agno.workflow.types import StepOutput

_LEADER_ERROR = "Simulated executor failure mid-stream"


def _sync_raising_stream(*args, **kwargs):
    raise RuntimeError(_LEADER_ERROR)
    yield  # pragma: no cover - makes this a generator


async def _async_raising_stream(*args, **kwargs):
    raise RuntimeError(_LEADER_ERROR)
    yield  # pragma: no cover - makes this an async generator


def _sync_raising_response(*args, **kwargs):
    raise RuntimeError(_LEADER_ERROR)


async def _async_raising_response(*args, **kwargs):
    raise RuntimeError(_LEADER_ERROR)


def _team_workflow() -> Workflow:
    member = Agent(name="Tool Agent", role="Runs tools", model=OpenAIChat(id="gpt-5.5"))
    orchestrator = Team(name="Orchestrator", model=OpenAIChat(id="gpt-5.5"), members=[member])
    return Workflow(name="Team-Workflow", steps=[orchestrator])


def _agent_workflow() -> Workflow:
    agent = Agent(name="Solo Agent", model=OpenAIChat(id="gpt-5.5"))
    return Workflow(name="Agent-Workflow", steps=[agent])


def _failing_step_output(completed_event: WorkflowCompletedEvent, step_name: str) -> StepOutput:
    assert completed_event is not None, "Workflow did not emit a WorkflowCompletedEvent"
    step_output = next(
        (s for s in (completed_event.step_results or []) if s.step_name == step_name),
        None,
    )
    assert step_output is not None, f"No StepOutput found for step '{step_name}'"
    return step_output


def _assert_failure_surfaced(step_output: StepOutput) -> None:
    # The executor failure must NOT be masked as a successful empty step.
    assert step_output.success is False
    assert step_output.error is not None
    assert _LEADER_ERROR in step_output.error


# =============================================================================
# Streaming paths -- the paths that regressed (issue #7185)
# =============================================================================


class TestStreamingExecutorErrorPropagation:
    def _run_sync_stream(self, workflow: Workflow) -> WorkflowCompletedEvent:
        completed_event = None
        for event in workflow.run(input="go", stream=True, stream_events=True):
            if isinstance(event, WorkflowCompletedEvent):
                completed_event = event
        return completed_event  # type: ignore[return-value]

    async def _run_async_stream(self, workflow: Workflow) -> WorkflowCompletedEvent:
        completed_event = None
        async for event in workflow.arun(input="go", stream=True, stream_events=True):
            if isinstance(event, WorkflowCompletedEvent):
                completed_event = event
        return completed_event  # type: ignore[return-value]

    def test_sync_stream_team_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.response_stream", new=_sync_raising_stream):
            completed = self._run_sync_stream(_team_workflow())
        _assert_failure_surfaced(_failing_step_output(completed, "Orchestrator"))

    @pytest.mark.asyncio
    async def test_async_stream_team_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.aresponse_stream", new=_async_raising_stream):
            completed = await self._run_async_stream(_team_workflow())
        _assert_failure_surfaced(_failing_step_output(completed, "Orchestrator"))

    def test_sync_stream_agent_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.response_stream", new=_sync_raising_stream):
            completed = self._run_sync_stream(_agent_workflow())
        _assert_failure_surfaced(_failing_step_output(completed, "Solo Agent"))

    @pytest.mark.asyncio
    async def test_async_stream_agent_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.aresponse_stream", new=_async_raising_stream):
            completed = await self._run_async_stream(_agent_workflow())
        _assert_failure_surfaced(_failing_step_output(completed, "Solo Agent"))


# =============================================================================
# Non-streaming paths -- regression guard (already correct before the fix)
# =============================================================================


class TestNonStreamingExecutorErrorPropagation:
    def test_sync_non_stream_team_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.response", new=_sync_raising_response):
            result = _team_workflow().run(input="go")
        _assert_failure_surfaced(_failing_step_output_from_result(result, "Orchestrator"))

    @pytest.mark.asyncio
    async def test_async_non_stream_team_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.aresponse", new=_async_raising_response):
            result = await _team_workflow().arun(input="go")
        _assert_failure_surfaced(_failing_step_output_from_result(result, "Orchestrator"))

    def test_sync_non_stream_agent_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.response", new=_sync_raising_response):
            result = _agent_workflow().run(input="go")
        _assert_failure_surfaced(_failing_step_output_from_result(result, "Solo Agent"))

    @pytest.mark.asyncio
    async def test_async_non_stream_agent_executor_error_surfaced(self):
        with patch("agno.models.openai.chat.OpenAIChat.aresponse", new=_async_raising_response):
            result = await _agent_workflow().arun(input="go")
        _assert_failure_surfaced(_failing_step_output_from_result(result, "Solo Agent"))


def _failing_step_output_from_result(result, step_name: str) -> StepOutput:
    step_output = next(
        (s for s in (result.step_results or []) if s.step_name == step_name),
        None,
    )
    assert step_output is not None, f"No StepOutput found for step '{step_name}'"
    return step_output

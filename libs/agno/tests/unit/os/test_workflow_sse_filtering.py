"""Unit tests for workflow SSE accumulator filtering.

Regression tests for https://github.com/agno-agi/agno/issues/8235

WorkflowRunOutput accumulator objects must be filtered out by the workflow
response streamers so they never reach format_sse_event (which expects
objects with an `.event` attribute, not `.events`).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.os.routers.workflows.router import (
    workflow_continue_response_streamer,
    workflow_response_streamer,
)
from agno.run.workflow import WorkflowRunOutput


def _make_accumulator_mock() -> MagicMock:
    """Create a mock that satisfies isinstance(obj, WorkflowRunOutput)."""
    return MagicMock(spec=WorkflowRunOutput)


def _make_event_mock(event_type: str = "WorkflowStarted") -> MagicMock:
    """Create a mock event object with `.event` attribute and `.to_json()`."""
    mock_event = MagicMock()
    mock_event.event = event_type
    mock_event.to_json.return_value = '{"event": "' + event_type + '"}'
    return mock_event


def _fake_format_sse_event(event) -> str:
    """Simple stand-in for format_sse_event: returns SSE-wrapped JSON."""
    return f"data: {event.to_json()}\n\n"


class TestWorkflowSSEAccumulatorFiltering:
    """Verify that WorkflowRunOutput accumulators are filtered and events pass through."""

    @pytest.mark.asyncio
    async def test_response_streamer_filters_workflow_run_output(self):
        """workflow_response_streamer must skip WorkflowRunOutput accumulator objects."""
        accumulator = _make_accumulator_mock()
        event = _make_event_mock()

        mock_workflow = MagicMock()

        # arun returns an async generator that yields accumulator then event
        async def _async_gen(*args, **kwargs):
            yield accumulator
            yield event

        mock_workflow.arun = MagicMock(return_value=_async_gen())
        # Avoid hitting the paused-workflow yield at end of streamer
        mock_workflow.get_session = MagicMock(return_value=None)

        collected = []
        with patch(
            "agno.os.routers.workflows.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in workflow_response_streamer(workflow=mock_workflow, input="hello"):
                collected.append(chunk)

        # Accumulator should have been skipped — format_sse_event called only once (for the event)
        assert mock_format.call_count == 1
        mock_format.assert_called_once_with(event)

        # Only the event's SSE string should be in the output
        assert len(collected) == 1
        assert "WorkflowStarted" in collected[0]

    @pytest.mark.asyncio
    async def test_response_streamer_passes_events(self):
        """workflow_response_streamer must yield valid WorkflowRunOutputEvent objects."""
        event1 = _make_event_mock("WorkflowStarted")
        event2 = _make_event_mock("StepStarted")
        event3 = _make_event_mock("WorkflowCompleted")

        mock_workflow = MagicMock()

        async def _async_gen(*args, **kwargs):
            yield event1
            yield event2
            yield event3

        mock_workflow.arun = MagicMock(return_value=_async_gen())
        mock_workflow.get_session = MagicMock(return_value=None)

        collected = []
        with patch(
            "agno.os.routers.workflows.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in workflow_response_streamer(workflow=mock_workflow, input="hello"):
                collected.append(chunk)

        # All three events should pass through
        assert mock_format.call_count == 3
        assert len(collected) == 3
        assert "WorkflowStarted" in collected[0]
        assert "StepStarted" in collected[1]
        assert "WorkflowCompleted" in collected[2]

    @pytest.mark.asyncio
    async def test_continue_response_streamer_filters_workflow_run_output(self):
        """workflow_continue_response_streamer must skip WorkflowRunOutput accumulator objects."""
        accumulator = _make_accumulator_mock()
        event = _make_event_mock()

        mock_workflow = MagicMock()

        # acontinue_run is awaited — it returns a coroutine that resolves to an async iterable
        async def _async_gen(*args, **kwargs):
            yield accumulator
            yield event

        # await workflow.acontinue_run(...) returns the async generator
        mock_workflow.acontinue_run = AsyncMock(return_value=_async_gen())
        mock_workflow.get_session = MagicMock(return_value=None)

        collected = []
        with patch(
            "agno.os.routers.workflows.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in workflow_continue_response_streamer(workflow=mock_workflow, run_id="test-run"):
                collected.append(chunk)

        # Accumulator filtered — format_sse_event called only for the event
        assert mock_format.call_count == 1
        mock_format.assert_called_once_with(event)

        assert len(collected) == 1
        assert "WorkflowStarted" in collected[0]

    @pytest.mark.asyncio
    async def test_continue_response_streamer_passes_events(self):
        """workflow_continue_response_streamer must yield valid WorkflowRunOutputEvent objects."""
        event1 = _make_event_mock("StepContinued")
        event2 = _make_event_mock("StepCompleted")
        event3 = _make_event_mock("WorkflowCompleted")

        mock_workflow = MagicMock()

        async def _async_gen(*args, **kwargs):
            yield event1
            yield event2
            yield event3

        mock_workflow.acontinue_run = AsyncMock(return_value=_async_gen())
        mock_workflow.get_session = MagicMock(return_value=None)

        collected = []
        with patch(
            "agno.os.routers.workflows.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in workflow_continue_response_streamer(workflow=mock_workflow, run_id="test-run"):
                collected.append(chunk)

        # All three events should pass through
        assert mock_format.call_count == 3
        assert len(collected) == 3
        assert "StepContinued" in collected[0]
        assert "StepCompleted" in collected[1]
        assert "WorkflowCompleted" in collected[2]

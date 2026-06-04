"""Unit tests for agent router accumulator filtering.

Regression tests for https://github.com/agno-agi/agno/issues/8235

Before the fix, RunOutput accumulator objects could leak into the SSE stream
via agent_response_streamer and agent_continue_response_streamer, causing
format_sse_event to crash with:

    AttributeError: 'RunOutput' object has no attribute 'event'

The isinstance filtering (`if isinstance(run_response_chunk, RunOutput): continue`)
ensures only RunOutputEvent objects reach format_sse_event.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.os.routers.agents.router import (
    agent_continue_response_streamer,
    agent_response_streamer,
)
from agno.run.agent import RunContentEvent, RunOutput, RunStartedEvent


def _make_run_output():
    """Create a MagicMock that satisfies isinstance(chunk, RunOutput)."""
    mock = MagicMock(spec=RunOutput)
    mock.events = []  # RunOutput has .events (plural), not .event
    return mock


def _make_run_started_event():
    """Create a real RunStartedEvent instance."""
    event = RunStartedEvent()
    return event


def _make_run_content_event(content="hello"):
    """Create a real RunContentEvent instance."""
    event = RunContentEvent(content=content)
    return event


async def _async_gen_run_output_and_events():
    """Async generator yielding a mix of RunOutput and RunOutputEvent objects."""
    yield _make_run_output()
    yield _make_run_started_event()
    yield _make_run_output()
    yield _make_run_content_event(content="world")
    yield _make_run_output()


async def _async_gen_events_only():
    """Async generator yielding only valid RunOutputEvent objects."""
    yield _make_run_started_event()
    yield _make_run_content_event(content="hello")
    yield _make_run_content_event(content="world")


class TestAgentSSEAccumulatorFiltering:
    """Tests that agent_response_streamer and agent_continue_response_streamer
    filter out RunOutput accumulator objects and only yield formatted SSE events
    for valid RunOutputEvent objects."""

    @pytest.mark.asyncio
    async def test_response_streamer_filters_run_output(self):
        """agent_response_streamer must skip RunOutput accumulator objects."""
        fake_agent = MagicMock()
        fake_agent.arun = MagicMock(return_value=_async_gen_run_output_and_events())

        collected = []
        with patch(
            "agno.os.routers.agents.router.format_sse_event",
            side_effect=lambda e: f"event: {getattr(e, 'event', 'msg')}\ndata: {{}}\n\n",
        ):
            async for chunk in agent_response_streamer(
                agent=fake_agent,
                message="test",
            ):
                collected.append(chunk)

        # RunOutput objects are filtered out, so only 2 events pass through
        assert len(collected) == 2

    @pytest.mark.asyncio
    async def test_response_streamer_passes_events(self):
        """agent_response_streamer must yield SSE strings for valid RunOutputEvent objects."""
        fake_agent = MagicMock()
        fake_agent.arun = MagicMock(return_value=_async_gen_events_only())

        format_calls = []

        def fake_format(event):
            format_calls.append(event)
            event_type = getattr(event, "event", "message")
            return f"event: {event_type}\ndata: {{}}\n\n"

        collected = []
        with patch(
            "agno.os.routers.agents.router.format_sse_event",
            side_effect=fake_format,
        ):
            async for chunk in agent_response_streamer(
                agent=fake_agent,
                message="test",
            ):
                collected.append(chunk)

        # All 3 events pass through
        assert len(collected) == 3
        # format_sse_event received exactly 3 calls with real event objects
        assert len(format_calls) == 3
        # None of the format_sse_event args are RunOutput instances
        for call_arg in format_calls:
            assert not isinstance(call_arg, RunOutput)

    @pytest.mark.asyncio
    async def test_continue_response_streamer_filters_run_output(self):
        """agent_continue_response_streamer must skip RunOutput accumulator objects."""
        fake_agent = MagicMock()
        fake_agent.acontinue_run = MagicMock(return_value=_async_gen_run_output_and_events())

        collected = []
        with patch(
            "agno.os.routers.agents.router.format_sse_event",
            side_effect=lambda e: f"event: {getattr(e, 'event', 'msg')}\ndata: {{}}\n\n",
        ):
            async for chunk in agent_continue_response_streamer(
                agent=fake_agent,
                run_id="test-run-id",
            ):
                collected.append(chunk)

        # RunOutput objects are filtered out, so only 2 events pass through
        assert len(collected) == 2

    @pytest.mark.asyncio
    async def test_continue_response_streamer_passes_events(self):
        """agent_continue_response_streamer must yield SSE strings for valid RunOutputEvent objects."""
        fake_agent = MagicMock()
        fake_agent.acontinue_run = MagicMock(return_value=_async_gen_events_only())

        format_calls = []

        def fake_format(event):
            format_calls.append(event)
            event_type = getattr(event, "event", "message")
            return f"event: {event_type}\ndata: {{}}\n\n"

        collected = []
        with patch(
            "agno.os.routers.agents.router.format_sse_event",
            side_effect=fake_format,
        ):
            async for chunk in agent_continue_response_streamer(
                agent=fake_agent,
                run_id="test-run-id",
            ):
                collected.append(chunk)

        # All 3 events pass through
        assert len(collected) == 3
        # format_sse_event received exactly 3 calls with real event objects
        assert len(format_calls) == 3
        # None of the format_sse_event args are RunOutput instances
        for call_arg in format_calls:
            assert not isinstance(call_arg, RunOutput)

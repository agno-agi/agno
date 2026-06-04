"""Unit tests for team SSE accumulator filtering.

Regression tests for https://github.com/agno-agi/agno/issues/8235

TeamRunOutput accumulator objects must be filtered out by the team
response streamers so they never reach format_sse_event (which expects
objects with an `.event` attribute, not `.events`).
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.os.routers.teams.router import (
    team_continue_response_streamer,
    team_response_streamer,
)
from agno.run.team import TeamRunOutput


def _make_accumulator_mock() -> MagicMock:
    """Create a mock that satisfies isinstance(obj, TeamRunOutput)."""
    return MagicMock(spec=TeamRunOutput)


def _make_event_mock(event_type: str = "TeamRunContent") -> MagicMock:
    """Create a mock event object with `.event` attribute and `.to_json()`."""
    mock_event = MagicMock()
    mock_event.event = event_type
    mock_event.to_json.return_value = '{"event": "' + event_type + '"}'
    return mock_event


def _fake_format_sse_event(event) -> str:
    """Simple stand-in for format_sse_event: returns SSE-wrapped JSON."""
    return f"data: {event.to_json()}\n\n"


class TestTeamSSEAccumulatorFiltering:
    """Verify that TeamRunOutput accumulators are filtered and events pass through."""

    @pytest.mark.asyncio
    async def test_response_streamer_filters_team_run_output(self):
        """team_response_streamer must skip TeamRunOutput accumulator objects."""
        accumulator = _make_accumulator_mock()
        event = _make_event_mock()

        mock_team = MagicMock()

        # arun returns an async generator that yields accumulator then event
        async def _async_gen(*args, **kwargs):
            yield accumulator
            yield event

        mock_team.arun = MagicMock(return_value=_async_gen())

        collected = []
        with patch(
            "agno.os.routers.teams.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in team_response_streamer(team=mock_team, message="hello"):
                collected.append(chunk)

        # Accumulator should have been skipped — format_sse_event called only once (for the event)
        assert mock_format.call_count == 1
        mock_format.assert_called_once_with(event)

        # Only the event's SSE string should be in the output
        assert len(collected) == 1
        assert "TeamRunContent" in collected[0]

    @pytest.mark.asyncio
    async def test_response_streamer_passes_events(self):
        """team_response_streamer must yield valid TeamRunOutputEvent objects."""
        event1 = _make_event_mock("TeamRunStarted")
        event2 = _make_event_mock("TeamRunContent")
        event3 = _make_event_mock("TeamRunCompleted")

        mock_team = MagicMock()

        async def _async_gen(*args, **kwargs):
            yield event1
            yield event2
            yield event3

        mock_team.arun = MagicMock(return_value=_async_gen())

        collected = []
        with patch(
            "agno.os.routers.teams.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in team_response_streamer(team=mock_team, message="hello"):
                collected.append(chunk)

        # All three events should pass through
        assert mock_format.call_count == 3
        assert len(collected) == 3
        assert "TeamRunStarted" in collected[0]
        assert "TeamRunContent" in collected[1]
        assert "TeamRunCompleted" in collected[2]

    @pytest.mark.asyncio
    async def test_continue_response_streamer_filters_team_run_output(self):
        """team_continue_response_streamer must skip TeamRunOutput accumulator objects."""
        accumulator = _make_accumulator_mock()
        event = _make_event_mock()

        mock_team = MagicMock()

        # acontinue_run returns an async generator
        async def _async_gen(*args, **kwargs):
            yield accumulator
            yield event

        mock_team.acontinue_run = MagicMock(return_value=_async_gen())

        collected = []
        with patch(
            "agno.os.routers.teams.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in team_continue_response_streamer(team=mock_team, run_id="test-run", requirements=[]):
                collected.append(chunk)

        # Accumulator filtered — format_sse_event called only for the event
        assert mock_format.call_count == 1
        mock_format.assert_called_once_with(event)

        assert len(collected) == 1
        assert "TeamRunContent" in collected[0]

    @pytest.mark.asyncio
    async def test_continue_response_streamer_passes_events(self):
        """team_continue_response_streamer must yield valid TeamRunOutputEvent objects."""
        event1 = _make_event_mock("TeamRunContinued")
        event2 = _make_event_mock("TeamRunContent")
        event3 = _make_event_mock("TeamRunCompleted")

        mock_team = MagicMock()

        async def _async_gen(*args, **kwargs):
            yield event1
            yield event2
            yield event3

        mock_team.acontinue_run = MagicMock(return_value=_async_gen())

        collected = []
        with patch(
            "agno.os.routers.teams.router.format_sse_event",
            side_effect=_fake_format_sse_event,
        ) as mock_format:
            async for chunk in team_continue_response_streamer(team=mock_team, run_id="test-run", requirements=[]):
                collected.append(chunk)

        # All three events should pass through
        assert mock_format.call_count == 3
        assert len(collected) == 3
        assert "TeamRunContinued" in collected[0]
        assert "TeamRunContent" in collected[1]
        assert "TeamRunCompleted" in collected[2]

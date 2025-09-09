from unittest.mock import MagicMock

import pytest
from ag_ui.core import EventType

from agno.os.interfaces.agui.utils import EventBuffer, async_stream_agno_response_as_agui_events
from agno.run.agent import RunContentEvent, ToolCallCompletedEvent, ToolCallStartedEvent


def test_event_buffer_initial_state():
    """Test EventBuffer initial state"""
    buffer = EventBuffer()

    assert not buffer.is_blocked()
    assert buffer.blocking_tool_call_id is None
    assert len(buffer.active_tool_call_ids) == 0
    assert len(buffer.ended_tool_call_ids) == 0
    assert len(buffer.buffer) == 0


def test_event_buffer_tool_call_lifecycle():
    """Test complete tool call lifecycle in EventBuffer"""
    buffer = EventBuffer()

    # Initial state
    assert not buffer.is_blocked()
    assert len(buffer.active_tool_call_ids) == 0

    # Start tool call
    buffer.start_tool_call("tool_1")
    assert buffer.is_blocked()
    assert buffer.blocking_tool_call_id == "tool_1"
    assert "tool_1" in buffer.active_tool_call_ids

    # End tool call
    unblocked = buffer.end_tool_call("tool_1")
    assert unblocked is True
    assert not buffer.is_blocked()
    assert "tool_1" in buffer.ended_tool_call_ids
    assert "tool_1" not in buffer.active_tool_call_ids


def test_event_buffer_multiple_tool_calls():
    """Test multiple concurrent tool calls"""
    buffer = EventBuffer()

    # Start first tool call (becomes blocking)
    buffer.start_tool_call("tool_1")
    assert buffer.blocking_tool_call_id == "tool_1"

    # Start second tool call (doesn't change blocking)
    buffer.start_tool_call("tool_2")
    assert buffer.blocking_tool_call_id == "tool_1"  # Still blocked by first
    assert len(buffer.active_tool_call_ids) == 2

    # End non-blocking tool call
    unblocked = buffer.end_tool_call("tool_2")
    assert unblocked is False
    assert buffer.is_blocked()  # Still blocked by tool_1
    assert buffer.blocking_tool_call_id == "tool_1"

    # End blocking tool call
    unblocked = buffer.end_tool_call("tool_1")
    assert unblocked is True
    assert not buffer.is_blocked()
    assert buffer.blocking_tool_call_id is None


def test_event_buffer_end_nonexistent_tool_call():
    """Test ending a tool call that was never started"""
    buffer = EventBuffer()

    # End tool call that was never started
    unblocked = buffer.end_tool_call("nonexistent_tool")
    assert unblocked is False
    assert not buffer.is_blocked()
    assert "nonexistent_tool" in buffer.ended_tool_call_ids


def test_event_buffer_duplicate_start_tool_call():
    """Test starting the same tool call multiple times"""
    buffer = EventBuffer()

    # Start same tool call twice
    buffer.start_tool_call("tool_1")
    buffer.start_tool_call("tool_1")  # Should not cause issues

    assert buffer.blocking_tool_call_id == "tool_1"
    assert len(buffer.active_tool_call_ids) == 1  # Should still be 1
    assert "tool_1" in buffer.active_tool_call_ids


def test_event_buffer_duplicate_end_tool_call():
    """Test ending the same tool call multiple times"""
    buffer = EventBuffer()

    buffer.start_tool_call("tool_1")

    # End same tool call twice
    unblocked_1 = buffer.end_tool_call("tool_1")
    unblocked_2 = buffer.end_tool_call("tool_1")

    assert unblocked_1 is True
    assert unblocked_2 is False  # Second end should not unblock
    assert not buffer.is_blocked()
    assert "tool_1" in buffer.ended_tool_call_ids


def test_event_buffer_complex_sequence():
    """Test complex sequence of tool call operations"""
    buffer = EventBuffer()

    # Start multiple tool calls
    buffer.start_tool_call("tool_1")  # This becomes blocking
    buffer.start_tool_call("tool_2")
    buffer.start_tool_call("tool_3")

    assert buffer.blocking_tool_call_id == "tool_1"
    assert len(buffer.active_tool_call_ids) == 3

    # End middle tool call (should not unblock)
    unblocked = buffer.end_tool_call("tool_2")
    assert unblocked is False
    assert buffer.is_blocked()
    assert buffer.blocking_tool_call_id == "tool_1"

    # End blocking tool call (should unblock)
    unblocked = buffer.end_tool_call("tool_1")
    assert unblocked is True
    assert not buffer.is_blocked()

    # End remaining tool call
    unblocked = buffer.end_tool_call("tool_3")
    assert unblocked is False  # Already unblocked

    # Check final state
    assert len(buffer.active_tool_call_ids) == 0
    assert len(buffer.ended_tool_call_ids) == 3


def test_event_buffer_blocking_behavior_edge_cases():
    """Test edge cases in blocking behavior"""
    buffer = EventBuffer()

    # Test that empty string tool_call_id is handled gracefully
    buffer.start_tool_call("")  # Empty string
    assert buffer.is_blocked()
    assert buffer.blocking_tool_call_id == ""

    # End with empty string
    unblocked = buffer.end_tool_call("")
    assert unblocked is True
    assert not buffer.is_blocked()


@pytest.mark.asyncio
async def test_stream_basic():
    """Test the async_stream_agno_response_as_agui_events function emits all expected events in a basic case."""
    from agno.run.agent import RunEvent

    async def mock_stream():
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "Hello world"
        yield text_response
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream(), "thread_1", "run_1"):
        events.append(event)

    assert len(events) == 4
    assert events[0].type == EventType.TEXT_MESSAGE_START
    assert events[1].type == EventType.TEXT_MESSAGE_CONTENT
    assert events[1].delta == "Hello world"
    assert events[2].type == EventType.TEXT_MESSAGE_END
    assert events[3].type == EventType.RUN_FINISHED


@pytest.mark.asyncio
async def test_stream_with_tool_call_blocking():
    """Test that events are properly buffered during tool calls"""
    from agno.run.agent import RunEvent

    async def mock_stream_with_tool_calls():
        # Start with a text response
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "I'll help you"
        yield text_response

        # Start a tool call
        tool_start_response = ToolCallStartedEvent()
        tool_start_response.event = RunEvent.tool_call_started
        tool_start_response.content = ""
        tool_call = MagicMock()
        tool_call.tool_call_id = "tool_1"
        tool_call.tool_name = "search"
        tool_call.tool_args = {"query": "test"}
        tool_start_response.tool = tool_call
        yield tool_start_response

        buffered_text_response = RunContentEvent()
        buffered_text_response.event = RunEvent.run_content
        buffered_text_response.content = "Searching..."
        yield buffered_text_response
        tool_end_response = ToolCallCompletedEvent()
        tool_end_response.event = RunEvent.tool_call_completed
        tool_end_response.content = ""
        tool_end_response.tool = tool_call
        yield tool_end_response
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_with_tool_calls(), "thread_1", "run_1"):
        events.append(event)

    # Asserting all expected events are present
    event_types = [event.type for event in events]
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_ARGS in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TEXT_MESSAGE_END in event_types
    assert EventType.RUN_FINISHED in event_types

    # Verify tool call ordering
    tool_start_idx = event_types.index(EventType.TOOL_CALL_START)
    tool_end_idx = event_types.index(EventType.TOOL_CALL_END)
    assert tool_start_idx < tool_end_idx

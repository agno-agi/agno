from unittest.mock import MagicMock

import pytest
from ag_ui.core import EventType

from agno.os.interfaces.agui.utils import EventBuffer, async_stream_agno_response_as_agui_events
from agno.run.agent import RunContentEvent, ToolCallCompletedEvent, ToolCallStartedEvent


def test_event_buffer_initial_state():
    """Test EventBuffer initial state"""
    buffer = EventBuffer()

    assert len(buffer.active_tool_call_ids) == 0
    assert len(buffer.ended_tool_call_ids) == 0


def test_event_buffer_tool_call_lifecycle():
    """Test complete tool call lifecycle in EventBuffer"""
    buffer = EventBuffer()

    # Initial state
    assert len(buffer.active_tool_call_ids) == 0

    # Start tool call
    buffer.start_tool_call("tool_1")
    assert "tool_1" in buffer.active_tool_call_ids

    # End tool call
    buffer.end_tool_call("tool_1")
    assert "tool_1" in buffer.ended_tool_call_ids
    assert "tool_1" not in buffer.active_tool_call_ids


def test_event_buffer_multiple_tool_calls():
    """Test multiple concurrent tool calls"""
    buffer = EventBuffer()

    # Start first tool call
    buffer.start_tool_call("tool_1")
    assert "tool_1" in buffer.active_tool_call_ids

    # Start second tool call
    buffer.start_tool_call("tool_2")
    assert len(buffer.active_tool_call_ids) == 2
    assert "tool_1" in buffer.active_tool_call_ids
    assert "tool_2" in buffer.active_tool_call_ids

    # End first tool call
    buffer.end_tool_call("tool_2")
    assert "tool_2" in buffer.ended_tool_call_ids
    assert "tool_2" not in buffer.active_tool_call_ids
    assert "tool_1" in buffer.active_tool_call_ids  # Still active

    # End second tool call
    buffer.end_tool_call("tool_1")
    assert "tool_1" in buffer.ended_tool_call_ids
    assert "tool_1" not in buffer.active_tool_call_ids
    assert len(buffer.active_tool_call_ids) == 0


def test_event_buffer_end_nonexistent_tool_call():
    """Test ending a tool call that was never started"""
    buffer = EventBuffer()

    # End tool call that was never started
    buffer.end_tool_call("nonexistent_tool")
    assert "nonexistent_tool" in buffer.ended_tool_call_ids


def test_event_buffer_duplicate_start_tool_call():
    """Test starting the same tool call multiple times"""
    buffer = EventBuffer()

    # Start same tool call twice
    buffer.start_tool_call("tool_1")
    buffer.start_tool_call("tool_1")  # Should not cause issues

    assert len(buffer.active_tool_call_ids) == 1  # Should still be 1
    assert "tool_1" in buffer.active_tool_call_ids


def test_event_buffer_duplicate_end_tool_call():
    """Test ending the same tool call multiple times"""
    buffer = EventBuffer()

    buffer.start_tool_call("tool_1")

    # End same tool call twice
    buffer.end_tool_call("tool_1")
    buffer.end_tool_call("tool_1")  # Second end should be no-op

    assert "tool_1" in buffer.ended_tool_call_ids
    assert "tool_1" not in buffer.active_tool_call_ids


def test_event_buffer_complex_sequence():
    """Test complex sequence of tool call operations"""
    buffer = EventBuffer()

    # Start multiple tool calls
    buffer.start_tool_call("tool_1")
    buffer.start_tool_call("tool_2")
    buffer.start_tool_call("tool_3")

    assert len(buffer.active_tool_call_ids) == 3

    # End middle tool call
    buffer.end_tool_call("tool_2")
    assert "tool_2" in buffer.ended_tool_call_ids
    assert len(buffer.active_tool_call_ids) == 2

    # End first tool call
    buffer.end_tool_call("tool_1")
    assert "tool_1" in buffer.ended_tool_call_ids

    # End remaining tool call
    buffer.end_tool_call("tool_3")
    assert "tool_3" in buffer.ended_tool_call_ids

    # Check final state
    assert len(buffer.active_tool_call_ids) == 0
    assert len(buffer.ended_tool_call_ids) == 3


def test_event_buffer_edge_cases():
    """Test edge cases in tool call handling"""
    buffer = EventBuffer()

    # Test that empty string tool_call_id is handled gracefully
    buffer.start_tool_call("")  # Empty string
    assert "" in buffer.active_tool_call_ids

    # End with empty string
    buffer.end_tool_call("")
    assert "" in buffer.ended_tool_call_ids
    assert "" not in buffer.active_tool_call_ids


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


@pytest.mark.asyncio
async def test_concurrent_tool_calls_no_infinite_loop():
    """Tests multiple concurrent tool calls without infinite loop"""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_three_concurrent_tools():
        # Initial text response
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "I'll check multiple stocks for you"
        yield text_response

        # Start 3 concurrent tool calls (this previously caused infinite loop)
        tool_call_1 = ToolExecution(
            tool_call_id="call_TSLA_123", tool_name="get_stock_price", tool_args={"symbol": "TSLA"}
        )
        tool_start_1 = ToolCallStartedEvent()
        tool_start_1.tool = tool_call_1
        yield tool_start_1

        tool_call_2 = ToolExecution(
            tool_call_id="call_AAPL_456", tool_name="get_stock_price", tool_args={"symbol": "AAPL"}
        )
        tool_start_2 = ToolCallStartedEvent()
        tool_start_2.tool = tool_call_2
        yield tool_start_2

        tool_call_3 = ToolExecution(
            tool_call_id="call_MSFT_789", tool_name="get_stock_price", tool_args={"symbol": "MSFT"}
        )
        tool_start_3 = ToolCallStartedEvent()
        tool_start_3.tool = tool_call_3
        yield tool_start_3

        # Some buffered content during tool calls
        buffered_response = RunContentEvent()
        buffered_response.event = RunEvent.run_content
        buffered_response.content = "Fetching stock data..."
        yield buffered_response

        # Complete all tool calls
        tool_call_1.result = {"price": 250.50, "symbol": "TSLA"}
        tool_end_1 = ToolCallCompletedEvent()
        tool_end_1.tool = tool_call_1
        yield tool_end_1

        tool_call_2.result = {"price": 175.25, "symbol": "AAPL"}
        tool_end_2 = ToolCallCompletedEvent()
        tool_end_2.tool = tool_call_2
        yield tool_end_2

        tool_call_3.result = {"price": 320.75, "symbol": "MSFT"}
        tool_end_3 = ToolCallCompletedEvent()
        tool_end_3.tool = tool_call_3
        yield tool_end_3

        # Final content and completion
        final_response = RunContentEvent()
        final_response.event = RunEvent.run_content
        final_response.content = "Here are the stock prices"
        yield final_response

        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_three_concurrent_tools(), "thread_1", "run_1"
    ):
        events.append(event)
        # Safety valve - if we get too many events, we might have an infinite loop
        if len(events) > 50:
            pytest.fail("Too many events generated - possible infinite loop detected")

    # Verify we got all expected events (should be around 19 events total)
    assert len(events) >= 15, f"Expected at least 15 events, got {len(events)}"

    event_types = [event.type for event in events]

    # Check all event types are present
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.TEXT_MESSAGE_END in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_ARGS in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TOOL_CALL_RESULT in event_types
    assert EventType.RUN_FINISHED in event_types

    # Verify we have events for all 3 tool calls
    tool_start_events = [e for e in events if e.type == EventType.TOOL_CALL_START]
    tool_end_events = [e for e in events if e.type == EventType.TOOL_CALL_END]
    assert len(tool_start_events) == 3, f"Expected 3 tool starts, got {len(tool_start_events)}"
    assert len(tool_end_events) == 3, f"Expected 3 tool ends, got {len(tool_end_events)}"


@pytest.mark.asyncio
async def test_text_message_end_before_tool_call_start():
    """
    Regression test for Issues #3554 and #4601: Missing TEXT_MESSAGE_END before TOOL_CALL_START.

    Tests that TEXT_MESSAGE_END is properly emitted before TOOL_CALL_START to prevent
    AG-UI protocol violations that cause errors like:
    "Cannot send event type 'TOOL_CALL_START' after 'TEXT_MESSAGE_START': Send 'TEXT_MESSAGE_END' first."
    """
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_text_then_tool():
        # Start with text content (this starts a TEXT_MESSAGE)
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "Let me check that for you"
        yield text_response

        # Immediately start a tool call (this should properly end the text message first)
        tool_call = ToolExecution(
            tool_call_id="call_search_123", tool_name="search_tool", tool_args={"query": "test query"}
        )
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool_call
        yield tool_start

        # Complete the tool call
        tool_call.result = {"results": "search results"}
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool_call
        yield tool_end

        # More text after tool call
        final_response = RunContentEvent()
        final_response.event = RunEvent.run_content
        final_response.content = "Based on the search results..."
        yield final_response

        # Complete the run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_text_then_tool(), "thread_1", "run_1"
    ):
        events.append(event)

    event_types = [event.type for event in events]

    # Find the indices of critical events
    text_start_idx = event_types.index(EventType.TEXT_MESSAGE_START)
    text_content_idx = event_types.index(EventType.TEXT_MESSAGE_CONTENT)
    text_end_idx = event_types.index(EventType.TEXT_MESSAGE_END)
    tool_start_idx = event_types.index(EventType.TOOL_CALL_START)

    # Verify proper ordering: TEXT_MESSAGE_END must come before TOOL_CALL_START
    assert text_start_idx < text_content_idx, "TEXT_MESSAGE_START should come before TEXT_MESSAGE_CONTENT"
    assert text_content_idx < text_end_idx, "TEXT_MESSAGE_CONTENT should come before TEXT_MESSAGE_END"
    assert text_end_idx < tool_start_idx, "TEXT_MESSAGE_END should come before TOOL_CALL_START (Issue #3554/#4601 fix)"

    # Ensure we have all expected event types
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.TEXT_MESSAGE_END in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_ARGS in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TOOL_CALL_RESULT in event_types
    assert EventType.RUN_FINISHED in event_types


@pytest.mark.asyncio
async def test_missing_text_message_content_events():
    """
    Regression test for Issue #3554: Missing TEXT_MESSAGE_CONTENT events.

    Tests that TEXT_MESSAGE_CONTENT events are properly emitted when the agent
    generates text content, ensuring the frontend UI shows the response content.
    """
    from agno.run.agent import RunEvent

    async def mock_stream_with_content():
        # Text response with actual content
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "Hello! How can I help you today?"
        yield text_response

        # Another chunk of content
        text_response2 = RunContentEvent()
        text_response2.event = RunEvent.run_content
        text_response2.content = " I'm here to assist with any questions."
        yield text_response2

        # Complete the run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_with_content(), "thread_1", "run_1"):
        events.append(event)

    # Filter for TEXT_MESSAGE_CONTENT events
    content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]

    # Should have TEXT_MESSAGE_CONTENT events (not empty like in the original issue)
    assert len(content_events) > 0, "Should have TEXT_MESSAGE_CONTENT events (Issue #3554 fix)"

    # Verify the content is properly captured
    total_content = "".join([e.delta for e in content_events])
    assert "Hello! How can I help you today?" in total_content
    assert "I'm here to assist with any questions." in total_content

    # Verify complete event sequence
    event_types = [event.type for event in events]
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types  # This was missing in Issue #3554
    assert EventType.TEXT_MESSAGE_END in event_types
    assert EventType.RUN_FINISHED in event_types


@pytest.mark.asyncio
async def test_duplicate_tool_call_result_events():
    """
    Regression test for Issue #3554: Duplicate ToolCallResultEvent with same results but different msg_id.

    Tests that tool call results are only emitted once per tool call completion.
    """
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_tool_completion():
        # Start a tool call
        tool_call = ToolExecution(tool_call_id="call_unique_123", tool_name="test_tool", tool_args={"param": "value"})
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool_call
        yield tool_start

        # Complete the tool call with a result
        tool_call.result = {"unique_result": "test_data", "id": "unique_123"}
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool_call
        yield tool_end

        # Complete the run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_tool_completion(), "thread_1", "run_1"
    ):
        events.append(event)

    # Filter for TOOL_CALL_RESULT events
    result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]

    # Should have exactly one TOOL_CALL_RESULT event (not duplicates)
    assert len(result_events) == 1, (
        f"Expected exactly 1 TOOL_CALL_RESULT event, got {len(result_events)} (Issue #3554 fix)"
    )

    # Verify the result content
    result_event = result_events[0]
    assert result_event.tool_call_id == "call_unique_123"
    assert "unique_result" in result_event.content
    assert "test_data" in result_event.content


@pytest.mark.asyncio
async def test_empty_content_chunks_handling():
    """Test that empty content chunks don't create unnecessary events"""
    from agno.run.agent import RunEvent

    async def mock_stream_with_empty_content():
        # Empty content chunk
        empty_response = RunContentEvent()
        empty_response.event = RunEvent.run_content
        empty_response.content = ""
        yield empty_response

        # None content chunk
        none_response = RunContentEvent()
        none_response.event = RunEvent.run_content
        none_response.content = None
        yield none_response

        # Valid content
        valid_response = RunContentEvent()
        valid_response.event = RunEvent.run_content
        valid_response.content = "Valid content"
        yield valid_response

        # Complete the run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_with_empty_content(), "thread_1", "run_1"):
        events.append(event)

    # Should only have content events for non-empty content
    content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    assert len(content_events) == 1, f"Expected 1 content event for non-empty content, got {len(content_events)}"
    assert content_events[0].delta == "Valid content"


@pytest.mark.asyncio
async def test_stream_ends_without_completion_event():
    """Test synthetic completion when stream ends naturally without completion event"""
    from agno.run.agent import RunEvent

    async def mock_stream_ending_abruptly():
        # Text response
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "Hello"
        yield text_response
        # Stream ends without RunCompleted event

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_ending_abruptly(), "thread_1", "run_1"):
        events.append(event)

    # Should have synthetic completion events
    event_types = [event.type for event in events]
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.TEXT_MESSAGE_END in event_types, "Should have synthetic TEXT_MESSAGE_END"
    assert EventType.RUN_FINISHED in event_types, "Should have synthetic RUN_FINISHED"


@pytest.mark.asyncio
async def test_reasoning_events_handling():
    """Test that reasoning events are properly converted to step events"""
    from agno.run.agent import RunEvent

    async def mock_stream_with_reasoning():
        # Start reasoning
        reasoning_start = RunContentEvent()
        reasoning_start.event = RunEvent.reasoning_started
        reasoning_start.content = ""
        yield reasoning_start

        # Some reasoning content
        reasoning_content = RunContentEvent()
        reasoning_content.event = RunEvent.run_content
        reasoning_content.content = "Thinking about this problem..."
        yield reasoning_content

        # End reasoning
        reasoning_end = RunContentEvent()
        reasoning_end.event = RunEvent.reasoning_completed
        reasoning_end.content = ""
        yield reasoning_end

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_with_reasoning(), "thread_1", "run_1"):
        events.append(event)

    event_types = [event.type for event in events]

    # Should have step events for reasoning
    assert EventType.STEP_STARTED in event_types, "Should have STEP_STARTED for reasoning"
    assert EventType.STEP_FINISHED in event_types, "Should have STEP_FINISHED for reasoning"

    # Should have text content during reasoning
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.RUN_FINISHED in event_types


@pytest.mark.asyncio
async def test_tool_call_without_result():
    """Test tool calls that complete without results (edge case)"""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_tool_no_result():
        # Start tool call
        tool_call = ToolExecution(tool_call_id="call_no_result", tool_name="void_tool", tool_args={"action": "ping"})
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool_call
        yield tool_start

        # Complete tool call without setting result (result=None)
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool_call
        yield tool_end

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_tool_no_result(), "thread_1", "run_1"):
        events.append(event)

    event_types = [event.type for event in events]

    # Should have tool call events
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_ARGS in event_types
    assert EventType.TOOL_CALL_END in event_types

    # Should NOT have TOOL_CALL_RESULT since result is None
    result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]
    assert len(result_events) == 0, (
        f"Expected no TOOL_CALL_RESULT events for tool with no result, got {len(result_events)}"
    )

    assert EventType.RUN_FINISHED in event_types


@pytest.mark.asyncio
async def test_mixed_content_and_tools_complex():
    """Complex test with interleaved content and tool calls (comprehensive scenario)"""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_complex_interleaved_stream():
        # Initial content
        initial_content = RunContentEvent()
        initial_content.event = RunEvent.run_content
        initial_content.content = "Starting analysis..."
        yield initial_content

        # Start first tool
        tool_1 = ToolExecution(tool_call_id="tool_1", tool_name="analyze", tool_args={"data": "A"})
        tool_start_1 = ToolCallStartedEvent()
        tool_start_1.tool = tool_1
        yield tool_start_1

        # More content while tool 1 is running
        middle_content = RunContentEvent()
        middle_content.event = RunEvent.run_content
        middle_content.content = "Processing data..."
        yield middle_content

        # Start second tool concurrently
        tool_2 = ToolExecution(tool_call_id="tool_2", tool_name="verify", tool_args={"check": "B"})
        tool_start_2 = ToolCallStartedEvent()
        tool_start_2.tool = tool_2
        yield tool_start_2

        # Complete first tool
        tool_1.result = "Analysis complete"
        tool_end_1 = ToolCallCompletedEvent()
        tool_end_1.tool = tool_1
        yield tool_end_1

        # More content after first tool
        post_tool_content = RunContentEvent()
        post_tool_content.event = RunEvent.run_content
        post_tool_content.content = "First analysis done..."
        yield post_tool_content

        # Complete second tool
        tool_2.result = "Verification passed"
        tool_end_2 = ToolCallCompletedEvent()
        tool_end_2.tool = tool_2
        yield tool_end_2

        # Final content
        final_content = RunContentEvent()
        final_content.event = RunEvent.run_content
        final_content.content = "All tasks completed!"
        yield final_content

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_complex_interleaved_stream(), "thread_1", "run_1"
    ):
        events.append(event)

    event_types = [event.type for event in events]

    # Verify all expected event types
    assert EventType.TEXT_MESSAGE_START in event_types
    assert EventType.TEXT_MESSAGE_CONTENT in event_types
    assert EventType.TEXT_MESSAGE_END in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_ARGS in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TOOL_CALL_RESULT in event_types
    assert EventType.RUN_FINISHED in event_types

    # Verify tool call counts
    tool_start_events = [e for e in events if e.type == EventType.TOOL_CALL_START]
    tool_end_events = [e for e in events if e.type == EventType.TOOL_CALL_END]
    tool_result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]

    assert len(tool_start_events) == 2, f"Expected 2 tool starts, got {len(tool_start_events)}"
    assert len(tool_end_events) == 2, f"Expected 2 tool ends, got {len(tool_end_events)}"
    assert len(tool_result_events) == 2, f"Expected 2 tool results, got {len(tool_result_events)}"

    # Verify content is properly captured and sequenced
    content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    total_content = "".join([e.delta for e in content_events])

    assert "Starting analysis..." in total_content
    assert "Processing data..." in total_content
    assert "First analysis done..." in total_content
    assert "All tasks completed!" in total_content

    # Verify TEXT_MESSAGE_END comes before RUN_FINISHED
    text_end_idx = event_types.index(EventType.TEXT_MESSAGE_END)
    run_finished_idx = event_types.index(EventType.RUN_FINISHED)
    assert text_end_idx < run_finished_idx, "TEXT_MESSAGE_END should come before RUN_FINISHED"


@pytest.mark.asyncio
async def test_large_scale_concurrent_tools():
    """Stress test with many concurrent tool calls to verify scalability"""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_many_tools():
        # Create 10 concurrent tool calls to stress test the system
        tools = []
        for i in range(10):
            tool = ToolExecution(tool_call_id=f"call_stress_{i}", tool_name=f"stress_tool_{i}", tool_args={"index": i})
            tools.append(tool)

            tool_start = ToolCallStartedEvent()
            tool_start.tool = tool
            yield tool_start

        # Complete all tools
        for i, tool in enumerate(tools):
            tool.result = f"Result {i}"
            tool_end = ToolCallCompletedEvent()
            tool_end.tool = tool
            yield tool_end

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_with_many_tools(), "thread_1", "run_1"):
        events.append(event)
        # Safety valve for stress test
        if len(events) > 100:
            pytest.fail("Too many events in stress test - possible infinite loop")

    # Verify expected number of events
    tool_start_events = [e for e in events if e.type == EventType.TOOL_CALL_START]
    tool_end_events = [e for e in events if e.type == EventType.TOOL_CALL_END]
    tool_result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]

    assert len(tool_start_events) == 10, f"Expected 10 tool starts, got {len(tool_start_events)}"
    assert len(tool_end_events) == 10, f"Expected 10 tool ends, got {len(tool_end_events)}"
    assert len(tool_result_events) == 10, f"Expected 10 tool results, got {len(tool_result_events)}"

    # Verify all tool call IDs are unique
    start_tool_ids = {e.tool_call_id for e in tool_start_events}
    end_tool_ids = {e.tool_call_id for e in tool_end_events}
    result_tool_ids = {e.tool_call_id for e in tool_result_events}

    assert len(start_tool_ids) == 10, "All tool call IDs should be unique"
    assert start_tool_ids == end_tool_ids == result_tool_ids, "Tool call IDs should match across event types"


@pytest.mark.asyncio
async def test_event_ordering_invariants():
    """Test critical event ordering invariants that must never be violated"""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_for_ordering():
        # Text content
        text_response = RunContentEvent()
        text_response.event = RunEvent.run_content
        text_response.content = "Processing your request"
        yield text_response

        # Tool call
        tool_call = ToolExecution(tool_call_id="order_test", tool_name="process", tool_args={})
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool_call
        yield tool_start

        tool_call.result = "Done"
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool_call
        yield tool_end

        # Final content
        final_text = RunContentEvent()
        final_text.event = RunEvent.run_content
        final_text.content = "Complete!"
        yield final_text

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(mock_stream_for_ordering(), "thread_1", "run_1"):
        events.append(event)

    event_types = [event.type for event in events]

    # Critical ordering invariants

    # 1. TEXT_MESSAGE_START must come before any TEXT_MESSAGE_CONTENT
    start_indices = [i for i, t in enumerate(event_types) if t == EventType.TEXT_MESSAGE_START]
    content_indices = [i for i, t in enumerate(event_types) if t == EventType.TEXT_MESSAGE_CONTENT]

    for start_idx in start_indices:
        related_content_indices = [i for i in content_indices if i > start_idx]
        if related_content_indices:
            next_end_idx = next(
                (i for i, t in enumerate(event_types[start_idx:], start_idx) if t == EventType.TEXT_MESSAGE_END),
                len(event_types),
            )
            related_content_indices = [i for i in related_content_indices if i < next_end_idx]
            for content_idx in related_content_indices:
                assert start_idx < content_idx, (
                    f"TEXT_MESSAGE_START at {start_idx} should come before TEXT_MESSAGE_CONTENT at {content_idx}"
                )

    # 2. TOOL_CALL_START must come before TOOL_CALL_ARGS for same tool
    tool_starts = [(i, e) for i, e in enumerate(events) if e.type == EventType.TOOL_CALL_START]
    tool_args = [(i, e) for i, e in enumerate(events) if e.type == EventType.TOOL_CALL_ARGS]

    for start_idx, start_event in tool_starts:
        matching_args = [(i, e) for i, e in tool_args if e.tool_call_id == start_event.tool_call_id]
        for args_idx, _ in matching_args:
            assert start_idx < args_idx, (
                f"TOOL_CALL_START at {start_idx} should come before TOOL_CALL_ARGS at {args_idx}"
            )

    # 3. RUN_FINISHED must be the last event
    run_finished_idx = event_types.index(EventType.RUN_FINISHED)
    assert run_finished_idx == len(event_types) - 1, "RUN_FINISHED must be the last event"


@pytest.mark.asyncio
async def test_completion_event_race_condition():
    """Test the specific race condition that was causing protocol violations"""
    from agno.run.agent import RunEvent

    async def mock_stream_with_race_condition():
        # Multiple content chunks
        for i in range(5):
            content_response = RunContentEvent()
            content_response.event = RunEvent.run_content
            content_response.content = f"Chunk {i} "
            yield content_response

        # Completion event with content (potential race condition)
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = "Final content in completion event"
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_race_condition(), "thread_1", "run_1"
    ):
        events.append(event)

    event_types = [event.type for event in events]

    # Verify proper sequence: all content, then TEXT_MESSAGE_END, then RUN_FINISHED
    text_end_idx = event_types.index(EventType.TEXT_MESSAGE_END)
    run_finished_idx = event_types.index(EventType.RUN_FINISHED)

    # All TEXT_MESSAGE_CONTENT events should come before TEXT_MESSAGE_END
    content_indices = [i for i, t in enumerate(event_types) if t == EventType.TEXT_MESSAGE_CONTENT]
    for content_idx in content_indices:
        assert content_idx < text_end_idx, (
            f"TEXT_MESSAGE_CONTENT at {content_idx} should come before TEXT_MESSAGE_END at {text_end_idx}"
        )

    # TEXT_MESSAGE_END should come before RUN_FINISHED
    assert text_end_idx < run_finished_idx, "TEXT_MESSAGE_END should come before RUN_FINISHED"

    # Verify content accumulation is correct
    content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    total_content = "".join([e.delta for e in content_events])

    # Should NOT include completion event content (this was the bug)
    assert "Final content in completion event" not in total_content, "Completion event content should not be duplicated"
    assert "Chunk 0 Chunk 1 Chunk 2 Chunk 3 Chunk 4 " == total_content, (
        "Content should be properly sequenced without duplication"
    )


@pytest.mark.asyncio
async def test_message_id_separation_after_tool_calls():
    """Test for text messages after tool calls should have different message_ids."""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_separated_messages():
        # First text message
        text_response_1 = RunContentEvent()
        text_response_1.event = RunEvent.run_content
        text_response_1.content = "Let me search for that information."
        yield text_response_1

        # Tool call starts (this should end first message and create new message_id)
        tool_call = ToolExecution(tool_call_id="search_123", tool_name="search_tool", tool_args={"query": "test"})
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool_call
        yield tool_start

        # Tool completes
        tool_call.result = {"results": "Found information"}
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool_call
        yield tool_end

        # Second text message (should have DIFFERENT message_id)
        text_response_2 = RunContentEvent()
        text_response_2.event = RunEvent.run_content
        text_response_2.content = "Based on the search results, here's what I found."
        yield text_response_2

        # Complete run
        completed_response = RunContentEvent()
        completed_response.event = RunEvent.run_completed
        completed_response.content = ""
        yield completed_response

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_separated_messages(), "thread_1", "run_1"
    ):
        events.append(event)

    # Extract relevant events
    text_start_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_START]
    text_content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    text_end_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_END]
    tool_call_start_events = [e for e in events if e.type == EventType.TOOL_CALL_START]

    # Verify we have expected number of events
    assert len(text_start_events) == 2, f"Expected 2 TEXT_MESSAGE_START events, got {len(text_start_events)}"
    assert len(text_content_events) == 2, f"Expected 2 TEXT_MESSAGE_CONTENT events, got {len(text_content_events)}"
    assert len(text_end_events) == 2, f"Expected 2 TEXT_MESSAGE_END events, got {len(text_end_events)}"
    assert len(tool_call_start_events) == 1, f"Expected 1 TOOL_CALL_START event, got {len(tool_call_start_events)}"

    # CORE ASSERTION: Different text messages should have different message_ids
    first_message_id = text_start_events[0].message_id
    second_message_id = text_start_events[1].message_id

    assert first_message_id != second_message_id, "Different text message segments should have different message_ids"

    # Verify content events match their respective start events
    assert text_content_events[0].message_id == first_message_id, "First content event should match first message_id"
    assert text_content_events[1].message_id == second_message_id, "Second content event should match second message_id"

    # Verify end events match their respective start events
    assert text_end_events[0].message_id == first_message_id, "First end event should match first message_id"
    assert text_end_events[1].message_id == second_message_id, "Second end event should match second message_id"

    # Verify tool call references correct parent message (the first message that was ended)
    tool_call_event = tool_call_start_events[0]
    assert tool_call_event.parent_message_id == first_message_id, (
        "Tool call should reference the first message as parent_message_id"
    )

    # Verify content matches expected text
    assert text_content_events[0].delta == "Let me search for that information."
    assert text_content_events[1].delta == "Based on the search results, here's what I found."


@pytest.mark.asyncio
async def test_multiple_tool_calls_message_id_separation():
    """
    Test that multiple tool calls properly separate messages with unique message_ids.
    """
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_stream_with_multiple_tools():
        # Initial text
        initial_text = RunContentEvent()
        initial_text.event = RunEvent.run_content
        initial_text.content = "I'll need to use multiple tools for this."
        yield initial_text

        # First tool call
        tool_1 = ToolExecution(tool_call_id="tool_1", tool_name="search", tool_args={"query": "A"})
        tool_start_1 = ToolCallStartedEvent()
        tool_start_1.tool = tool_1
        yield tool_start_1

        tool_1.result = "Result A"
        tool_end_1 = ToolCallCompletedEvent()
        tool_end_1.tool = tool_1
        yield tool_end_1

        # Text between tools
        middle_text = RunContentEvent()
        middle_text.event = RunEvent.run_content
        middle_text.content = "Now let me try another approach."
        yield middle_text

        # Second tool call
        tool_2 = ToolExecution(tool_call_id="tool_2", tool_name="calculate", tool_args={"expr": "2+2"})
        tool_start_2 = ToolCallStartedEvent()
        tool_start_2.tool = tool_2
        yield tool_start_2

        tool_2.result = "4"
        tool_end_2 = ToolCallCompletedEvent()
        tool_end_2.tool = tool_2
        yield tool_end_2

        # Final text
        final_text = RunContentEvent()
        final_text.event = RunEvent.run_content
        final_text.content = "Based on both results, here's my conclusion."
        yield final_text

        # Complete
        completed = RunContentEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        yield completed

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_multiple_tools(), "thread_1", "run_1"
    ):
        events.append(event)

    # Extract events
    text_start_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_START]
    text_content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    tool_call_start_events = [e for e in events if e.type == EventType.TOOL_CALL_START]

    # Should have 3 text messages: initial, middle, final
    assert len(text_start_events) == 3, f"Expected 3 text messages, got {len(text_start_events)}"
    assert len(text_content_events) == 3, f"Expected 3 text content events, got {len(text_content_events)}"
    assert len(tool_call_start_events) == 2, f"Expected 2 tool calls, got {len(tool_call_start_events)}"

    # All message_ids should be different
    message_ids = [event.message_id for event in text_start_events]
    assert len(set(message_ids)) == 3, f"All message_ids should be unique, got: {message_ids}"

    # Tool calls should reference correct parent messages
    first_tool_parent = tool_call_start_events[0].parent_message_id
    second_tool_parent = tool_call_start_events[1].parent_message_id

    assert first_tool_parent == message_ids[0], "First tool should reference first message"
    assert second_tool_parent == message_ids[1], "Second tool should reference second message"

    # Content should match expected messages
    expected_content = [
        "I'll need to use multiple tools for this.",
        "Now let me try another approach.",
        "Based on both results, here's my conclusion.",
    ]
    actual_content = [event.delta for event in text_content_events]
    assert actual_content == expected_content, f"Content mismatch: {actual_content}"


@pytest.mark.asyncio
async def test_message_id_consistency_within_message():
    """
    Test that all events within a single message (start, content chunks, end) use the same message_id.
    """
    from agno.run.agent import RunEvent

    async def mock_stream_with_chunked_content():
        # Multiple content chunks for first message
        chunk1 = RunContentEvent()
        chunk1.event = RunEvent.run_content
        chunk1.content = "This is "
        yield chunk1

        chunk2 = RunContentEvent()
        chunk2.event = RunEvent.run_content
        chunk2.content = "a long message "
        yield chunk2

        chunk3 = RunContentEvent()
        chunk3.event = RunEvent.run_content
        chunk3.content = "with multiple chunks."
        yield chunk3

        # Complete
        completed = RunContentEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        yield completed

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_stream_with_chunked_content(), "thread_1", "run_1"
    ):
        events.append(event)

    # Extract message-related events
    text_start_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_START]
    text_content_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT]
    text_end_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_END]

    assert len(text_start_events) == 1, "Should have exactly one message"
    assert len(text_content_events) == 3, "Should have 3 content chunks"
    assert len(text_end_events) == 1, "Should have exactly one end event"

    # All events should use the same message_id
    message_id = text_start_events[0].message_id

    for event in text_content_events:
        assert event.message_id == message_id, (
            f"Content event message_id {event.message_id} should match start event {message_id}"
        )

    assert text_end_events[0].message_id == message_id, f"End event message_id should match start event {message_id}"

    # Content should be properly concatenated
    total_content = "".join([e.delta for e in text_content_events])
    assert total_content == "This is a long message with multiple chunks."


@pytest.mark.asyncio
async def test_message_id_regression_prevention():
    """
    Regression test for message_id separation across tool call boundaries.

    Ensures that text messages separated by tool calls maintain unique message_ids,
    preventing improper message grouping in AG-UI frontends.
    """
    from agno.models.response import ToolExecution
    from agno.run.agent import RunEvent

    async def mock_complex_message_tool_sequence():
        # Text before tool call
        text1 = RunContentEvent()
        text1.event = RunEvent.run_content
        text1.content = "Let me help you with that."
        yield text1

        # Tool call
        tool = ToolExecution(tool_call_id="bug_test", tool_name="helper", tool_args={})
        tool_start = ToolCallStartedEvent()
        tool_start.tool = tool
        yield tool_start

        tool.result = "success"
        tool_end = ToolCallCompletedEvent()
        tool_end.tool = tool
        yield tool_end

        # Text after tool call - should have different message_id
        text2 = RunContentEvent()
        text2.event = RunEvent.run_content
        text2.content = "Based on the results, here's your answer."
        yield text2

        # Another tool call
        tool2 = ToolExecution(tool_call_id="bug_test_2", tool_name="finalizer", tool_args={})
        tool_start_2 = ToolCallStartedEvent()
        tool_start_2.tool = tool2
        yield tool_start_2

        tool2.result = "done"
        tool_end_2 = ToolCallCompletedEvent()
        tool_end_2.tool = tool2
        yield tool_end_2

        # Final text - should also have different message_id
        text3 = RunContentEvent()
        text3.event = RunEvent.run_content
        text3.content = "All done!"
        yield text3

        # Complete
        completed = RunContentEvent()
        completed.event = RunEvent.run_completed
        completed.content = ""
        yield completed

    events = []
    async for event in async_stream_agno_response_as_agui_events(
        mock_complex_message_tool_sequence(), "thread_1", "run_1"
    ):
        events.append(event)

    # Extract events
    text_start_events = [e for e in events if e.type == EventType.TEXT_MESSAGE_START]
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL_START]

    # Should have 3 distinct text messages
    assert len(text_start_events) == 3, f"Expected 3 text messages, got {len(text_start_events)}"
    assert len(tool_call_events) == 2, f"Expected 2 tool calls, got {len(tool_call_events)}"

    # Extract all message_ids
    message_ids = [event.message_id for event in text_start_events]

    # CRITICAL: All message_ids must be different
    assert len(set(message_ids)) == 3, (
        f"All text message_ids should be unique across tool call boundaries. Got message_ids: {message_ids}"
    )

    # Tool calls should reference correct parent messages
    tool_1_parent = tool_call_events[0].parent_message_id
    tool_2_parent = tool_call_events[1].parent_message_id

    assert tool_1_parent == message_ids[0], (
        f"First tool call should reference first message. Expected {message_ids[0]}, got {tool_1_parent}"
    )
    assert tool_2_parent == message_ids[1], (
        f"Second tool call should reference second message. Expected {message_ids[1]}, got {tool_2_parent}"
    )

    # Verify no message_id is reused
    all_referenced_ids = set(message_ids + [tool_1_parent, tool_2_parent])
    assert len(all_referenced_ids) == 3, (
        f"Should have exactly 3 unique message IDs in the conversation. Found: {sorted(all_referenced_ids)}"
    )


def test_validate_agui_state_with_valid_dict():
    """Test validate_agui_state with valid dict."""
    from agno.os.interfaces.agui.utils import validate_agui_state

    result = validate_agui_state({"user_name": "Alice", "counter": 5}, "test_thread")
    assert result == {"user_name": "Alice", "counter": 5}


def test_validate_agui_state_with_none():
    """Test validate_agui_state with None state."""
    from agno.os.interfaces.agui.utils import validate_agui_state

    result = validate_agui_state(None, "test_thread")
    assert result is None


def test_validate_agui_state_with_invalid_type():
    """Test validate_agui_state with non-dict type returns None."""
    from agno.os.interfaces.agui.utils import validate_agui_state

    # String state should be rejected
    result = validate_agui_state("invalid_string", "test_thread")
    assert result is None
    # List state should be rejected
    result = validate_agui_state([1, 2, 3], "test_thread")
    assert result is None
    # Number state should be rejected
    result = validate_agui_state(42, "test_thread")
    assert result is None


def test_validate_agui_state_with_basemodel():
    """Test validate_agui_state with Pydantic BaseModel."""
    from pydantic import BaseModel

    from agno.os.interfaces.agui.utils import validate_agui_state

    class TestModel(BaseModel):
        name: str
        count: int

    model = TestModel(name="test", count=10)
    result = validate_agui_state(model, "test_thread")
    assert result == {"name": "test", "count": 10}


def test_validate_agui_state_with_dataclass():
    """Test validate_agui_state with dataclass."""
    from dataclasses import dataclass

    from agno.os.interfaces.agui.utils import validate_agui_state

    @dataclass
    class TestDataclass:
        name: str
        count: int

    data = TestDataclass(name="test", count=10)
    result = validate_agui_state(data, "test_thread")
    assert result == {"name": "test", "count": 10}


def test_validate_agui_state_with_to_dict_method():
    """Test validate_agui_state with object having to_dict method."""
    from agno.os.interfaces.agui.utils import validate_agui_state

    class TestClass:
        def __init__(self, name: str, count: int):
            self.name = name
            self.count = count

        def to_dict(self):
            return {"name": self.name, "count": self.count}

    obj = TestClass(name="test", count=10)
    result = validate_agui_state(obj, "test_thread")
    assert result == {"name": "test", "count": 10}


def test_validate_agui_state_with_invalid_to_dict():
    """Test validate_agui_state with to_dict method returning non-dict."""
    from agno.os.interfaces.agui.utils import validate_agui_state

    class TestClass:
        def to_dict(self):
            return "not_a_dict"

    obj = TestClass()
    result = validate_agui_state(obj, "test_thread")
    assert result is None

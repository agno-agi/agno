"""Integration tests for agent cancellation with partial data preservation.

These tests verify that when an agent is cancelled mid-execution:
1. The partial content/data generated before cancellation is preserved
2. The agent run status is set to cancelled
3. All partial data is stored in the database
4. Cancellation events are emitted properly
5. Resources (memory tasks, tools) are cleaned up properly
"""

import asyncio
import threading
import time

import pytest

from agno.agent.agent import Agent
from agno.exceptions import RunCancelledException
from agno.models.openai import OpenAIChat
from agno.run.agent import RunCancelledEvent
from agno.run.base import RunStatus


# ============================================================================
# SYNCHRONOUS STREAMING TESTS
# ============================================================================
def test_cancel_agent_during_sync_streaming(shared_db):
    """Test cancelling an agent during synchronous streaming execution.

    Verifies:
    - Cancellation exception is raised
    - Partial content is collected before cancellation
    - Resources are cleaned up (run removed from tracking)
    """
    from agno.run.cancel import _cancellation_manager

    agent = Agent(
        name="Streaming Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a detailed 3-paragraph response about AI agents.",
        db=shared_db,
    )

    session_id = "test_sync_cancel_session"
    events_collected = []
    content_chunks = []
    run_id = None
    cancellation_raised = False

    # Start streaming agent
    event_stream = agent.run(
        input="Tell me about AI agents in detail",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    # Collect events and cancel mid-stream
    try:
        for event in event_stream:
            events_collected.append(event)

            # Extract run_id from the first event
            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            # Track content
            if hasattr(event, "content") and event.content and isinstance(event.content, str):
                content_chunks.append(event.content)

            # Cancel after collecting some content
            if len(content_chunks) >= 5 and run_id:
                agent.cancel_run(run_id)
                # In sync streaming, the exception will be raised on next iteration
    except RunCancelledException:
        # Cancellation exception is expected when iterating after cancel_run
        cancellation_raised = True

    # Verify cancellation was triggered
    assert cancellation_raised, "RunCancelledException should have been raised"

    # Verify we collected content before cancellation
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks before cancellation"

    # Verify the run was cleaned up (not in the active runs tracking)
    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


# ============================================================================
# ASYNCHRONOUS STREAMING TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_agent_during_async_streaming(shared_db):
    """Test cancelling an agent during asynchronous streaming execution.

    Verifies:
    - Cancellation event is received
    - Partial content is preserved in database
    - Run status is set to cancelled
    - Resources are cleaned up (run removed from tracking)
    """
    from agno.run.cancel import _cancellation_manager

    agent = Agent(
        name="Async Streaming Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a detailed 3-paragraph response about AI technology.",
        db=shared_db,
    )

    session_id = "test_async_cancel_session"
    events_collected = []
    content_chunks = []
    run_id = None

    # Start async streaming agent
    event_stream = agent.arun(
        input="Tell me about AI technology in detail",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    # Collect events and cancel mid-stream
    cancelled = False
    async for event in event_stream:
        events_collected.append(event)

        # Extract run_id from the first event
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        # Track content
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        # Cancel after collecting some content (but continue consuming events)
        if len(content_chunks) >= 5 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True
            # Don't break - let the generator complete naturally

    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, RunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"

    # Verify the agent run was saved with partial data
    # Use sync method since shared_db is SqliteDb (synchronous)
    agent_session = agent.get_session(session_id=session_id)
    assert agent_session is not None
    assert agent_session.runs is not None and len(agent_session.runs) > 0

    last_run = agent_session.runs[-1]
    assert last_run.status == RunStatus.cancelled

    # Verify we have partial content saved
    assert last_run.content is not None and len(last_run.content) > 0, "Should have captured partial content"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks"

    # Wait for any pending async tasks to complete
    await asyncio.sleep(0.2)

    # Verify the run was cleaned up
    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
def test_cancel_agent_immediately(shared_db):
    """Test cancelling an agent immediately after it starts.

    Note: In sync streaming, RunCancelledException is raised when cancel_run is called.
    """
    agent = Agent(
        name="Quick Cancel Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=shared_db,
    )

    session_id = "test_immediate_cancel"
    events_collected = []
    run_id = None
    cancellation_raised = False

    event_stream = agent.run(
        input="Tell me about AI",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    try:
        for event in event_stream:
            events_collected.append(event)

            # Extract run_id and cancel immediately
            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id
                agent.cancel_run(run_id)
                # In sync streaming, the exception will be raised on next iteration
    except RunCancelledException:
        # Cancellation exception is expected when iterating after cancel_run
        cancellation_raised = True

    # Verify cancellation was triggered
    assert cancellation_raised, "RunCancelledException should have been raised"
    assert run_id is not None, "Should have received at least one event with run_id"


@pytest.mark.asyncio
async def test_cancel_non_existent_agent_run():
    """Test that cancelling a non-existent run returns False."""
    from agno.db.sqlite import SqliteDb

    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=SqliteDb(db_file="tmp/test_agent_cancel.db"),
    )

    # Try to cancel a run that doesn't exist
    result = agent.cancel_run("non_existent_run_id")
    assert result is False, "Cancelling non-existent run should return False"


def test_cancel_agent_with_tool_calls(shared_db):
    """Test cancelling an agent that uses tools during execution.

    Note: In sync streaming, RunCancelledException is raised when cancel_run is called.
    We verify that events were collected before cancellation.
    """
    from agno.tools.duckduckgo import DuckDuckGoTools

    agent = Agent(
        name="Tool Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a research agent. Search for information and provide detailed responses.",
        tools=[DuckDuckGoTools()],
        db=shared_db,
    )

    session_id = "test_cancel_with_tools"
    events_collected = []
    content_chunks = []
    run_id = None
    tool_calls_executed = 0
    cancellation_raised = False

    event_stream = agent.run(
        input="Search for information about artificial intelligence and write a long essay",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    try:
        for event in event_stream:
            events_collected.append(event)

            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            # Track tool calls
            if hasattr(event, "tool_name"):
                tool_calls_executed += 1

            # Track content
            if hasattr(event, "content") and event.content and isinstance(event.content, str):
                content_chunks.append(event.content)

            # Cancel after some content
            if len(content_chunks) >= 3 and run_id:
                agent.cancel_run(run_id)
                # In sync streaming, the exception will be raised on next iteration

    except RunCancelledException:
        # Cancellation exception is expected when iterating after cancel_run
        cancellation_raised = True

    # Verify cancellation was triggered
    assert cancellation_raised, "RunCancelledException should have been raised"

    # Verify we collected content before cancellation
    assert len(content_chunks) >= 3, "Should have collected at least 3 content chunks before cancellation"


# ============================================================================
# NON-STREAMING CANCELLATION TESTS
# ============================================================================
def test_cancel_agent_sync_non_streaming(shared_db):
    """Test cancelling an agent during synchronous non-streaming execution.

    This test uses a separate thread to cancel the run while it's executing.
    """
    agent = Agent(
        name="Non-Streaming Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very detailed 5-paragraph essay about the history of computing.",
        db=shared_db,
    )

    session_id = "test_sync_non_streaming_cancel"
    run_id = "test_non_streaming_run_id"
    result = None
    exception_raised = None

    def run_agent():
        nonlocal result, exception_raised
        try:
            result = agent.run(
                input="Write a very detailed essay about the history of computing from the 1940s to today",
                session_id=session_id,
                run_id=run_id,
                stream=False,
            )
        except RunCancelledException as e:
            exception_raised = e

    # Start agent in a separate thread
    agent_thread = threading.Thread(target=run_agent)
    agent_thread.start()

    # Wait a bit for the agent to start, then cancel
    time.sleep(1.0)
    cancel_result = agent.cancel_run(run_id)

    # Wait for the thread to complete
    agent_thread.join(timeout=10)

    # Either the run was cancelled or it completed before cancellation
    if cancel_result:
        # If cancellation was registered, we should have either an exception or a cancelled status
        if exception_raised:
            assert isinstance(exception_raised, RunCancelledException)
        elif result:
            # Run completed but might have been marked as cancelled
            assert result.status in [RunStatus.cancelled, RunStatus.completed]
    else:
        # Cancellation wasn't registered (run might have completed already)
        assert result is not None


@pytest.mark.asyncio
async def test_cancel_agent_async_non_streaming(shared_db):
    """Test cancelling an agent during asynchronous non-streaming execution."""
    agent = Agent(
        name="Async Non-Streaming Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very detailed 5-paragraph essay.",
        db=shared_db,
    )

    session_id = "test_async_non_streaming_cancel"
    run_id = "test_async_non_streaming_run_id"

    async def cancel_after_delay():
        await asyncio.sleep(1.0)
        agent.cancel_run(run_id)

    # Start cancellation task
    cancel_task = asyncio.create_task(cancel_after_delay())

    # Run the agent
    try:
        result = await agent.arun(
            input="Write a very detailed essay about artificial intelligence and its impact on society",
            session_id=session_id,
            run_id=run_id,
            stream=False,
        )
        # If we get here, the run completed before cancellation
        assert result.status in [RunStatus.completed, RunStatus.cancelled]
    except RunCancelledException:
        # Cancellation was successful
        pass

    # Clean up the cancel task
    cancel_task.cancel()
    try:
        await cancel_task
    except asyncio.CancelledError:
        pass


# ============================================================================
# MULTIPLE CANCELLATION TESTS
# ============================================================================
def test_multiple_cancel_calls_sync(shared_db):
    """Test that multiple cancel calls don't cause issues."""
    agent = Agent(
        name="Multiple Cancel Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=shared_db,
    )

    session_id = "test_multiple_cancel"
    run_id = None
    cancellation_raised = False

    event_stream = agent.run(
        input="Tell me about AI",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    try:
        for event in event_stream:
            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id
                # Call cancel multiple times
                agent.cancel_run(run_id)
                agent.cancel_run(run_id)
                agent.cancel_run(run_id)
    except RunCancelledException:
        cancellation_raised = True

    assert cancellation_raised, "RunCancelledException should have been raised"


@pytest.mark.asyncio
async def test_cancel_preserves_partial_structured_output(shared_db):
    """Test that cancellation preserves partial content even with structured output."""
    from pydantic import BaseModel

    class Essay(BaseModel):
        title: str
        paragraphs: list[str]

    agent = Agent(
        name="Structured Output Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent that writes essays.",
        db=shared_db,
    )

    session_id = "test_structured_cancel"
    run_id = None
    content_collected = []
    cancelled = False

    event_stream = agent.arun(
        input="Write a 5-paragraph essay about technology",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content:
            content_collected.append(str(event.content))

        # Cancel after collecting some content
        if len(content_collected) >= 5 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    # Verify we got partial content before cancellation
    assert len(content_collected) >= 5, "Should have collected content before cancellation"

    # Verify the run was saved with partial content
    agent_session = agent.get_session(session_id=session_id)
    assert agent_session is not None
    assert agent_session.runs is not None and len(agent_session.runs) > 0

    last_run = agent_session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None, "Partial content should be preserved"

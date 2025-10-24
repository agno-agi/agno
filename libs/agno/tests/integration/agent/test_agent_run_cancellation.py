"""Integration tests for agent cancellation with partial data preservation.

These tests verify that when an agent is cancelled mid-execution:
1. The partial content/data generated before cancellation is preserved
2. The agent run status is set to cancelled
3. All partial data is stored in the database
4. Cancellation events are emitted properly
"""

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.agent import RunCancelledEvent


# ============================================================================
# SYNCHRONOUS STREAMING TESTS
# ============================================================================
def test_cancel_agent_during_sync_streaming(shared_db):
    """Test cancelling an agent during synchronous streaming execution."""
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
    
    # Start streaming agent
    event_stream = agent.run(
        input="Tell me about AI agents in detail",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )
    
    # Collect events and cancel mid-stream
    for event in event_stream:
        events_collected.append(event)
        
        # Extract run_id from the first event
        if run_id is None and hasattr(event, 'run_id'):
            run_id = event.run_id
        
        # Track content
        if hasattr(event, 'content') and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        
        # Cancel after collecting some content
        if len(content_chunks) >= 5 and run_id:
            agent.cancel_run(run_id)
            # Continue collecting remaining events
            try:
                for remaining_event in event_stream:
                    events_collected.append(remaining_event)
            except StopIteration:
                pass
            break
    
    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, RunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    
    # Verify the agent run was saved with partial data
    agent_session = agent.get_session(session_id=session_id)
    assert agent_session is not None
    assert agent_session.runs is not None and len(agent_session.runs) > 0
    
    last_run = agent_session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    
    # Verify we have partial content saved
    assert last_run.content is not None and len(last_run.content) > 0, "Should have captured partial content"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks"
    
    # The partial content should match what we collected
    assert len(last_run.content) > 0, "Partial content should be preserved in database"


# ============================================================================
# ASYNCHRONOUS STREAMING TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_agent_during_async_streaming(shared_db):
    """Test cancelling an agent during asynchronous streaming execution."""
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
        if run_id is None and hasattr(event, 'run_id'):
            run_id = event.run_id
        
        # Track content
        if hasattr(event, 'content') and event.content and isinstance(event.content, str):
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
    import asyncio
    await asyncio.sleep(0.1)


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
def test_cancel_agent_immediately(shared_db):
    """Test cancelling an agent immediately after it starts."""
    agent = Agent(
        name="Quick Cancel Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=shared_db,
    )
    
    session_id = "test_immediate_cancel"
    events_collected = []
    run_id = None
    
    event_stream = agent.run(
        input="Tell me about AI",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )
    
    for event in event_stream:
        events_collected.append(event)
        
        # Extract run_id and cancel immediately
        if run_id is None and hasattr(event, 'run_id'):
            run_id = event.run_id
            agent.cancel_run(run_id)
            # Continue collecting remaining events
            try:
                for remaining_event in event_stream:
                    events_collected.append(remaining_event)
            except StopIteration:
                pass
            break
    
    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, RunCancelledEvent)]
    assert len(cancelled_events) == 1
    
    # Verify the agent run was saved
    agent_session = agent.get_session(session_id=session_id)
    last_run = agent_session.runs[-1]
    assert last_run.status == RunStatus.cancelled


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
    """Test that tool calls executed before cancellation are preserved."""
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
    
    event_stream = agent.run(
        input="Search for information about artificial intelligence and write a long essay",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )
    
    for event in event_stream:
        events_collected.append(event)
        
        if run_id is None and hasattr(event, 'run_id'):
            run_id = event.run_id
        
        # Track tool calls
        if hasattr(event, 'tool_name'):
            tool_calls_executed += 1
        
        # Track content
        if hasattr(event, 'content') and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        
        # Cancel after some content
        if len(content_chunks) >= 3 and run_id:
            agent.cancel_run(run_id)
            try:
                for remaining_event in event_stream:
                    events_collected.append(remaining_event)
            except StopIteration:
                pass
            break
    
    # Verify the agent run was saved
    agent_session = agent.get_session(session_id=session_id)
    last_run = agent_session.runs[-1]
    
    assert last_run.status == RunStatus.cancelled
    # If any tools were executed, they should be preserved
    if tool_calls_executed > 0:
        assert last_run.tools is not None and len(last_run.tools) > 0, "Tool calls should be preserved"


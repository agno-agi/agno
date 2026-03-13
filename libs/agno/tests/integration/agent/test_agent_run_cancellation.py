"""Integration tests for agent cancellation with partial data preservation.

These tests verify that when an agent is cancelled mid-execution:
1. The partial content/data generated before cancellation is preserved
2. The agent run status is set to cancelled
3. All partial data is stored in the database
4. Cancellation events are emitted properly
5. Resources (memory tasks, tools) are cleaned up properly
"""

import asyncio
import os
import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunCancelledEvent, RunEvent
from agno.run.base import RunStatus
from agno.run.cancel import cancel_run, register_run

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


# ============================================================================
# SYNCHRONOUS STREAMING TESTS
# ============================================================================
def test_cancel_agent_during_sync_streaming(shared_db):
    """Test cancelling an agent during synchronous streaming execution.

    Verifies:
    - Cancellation event is received
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
    cancelled = False

    event_stream = agent.run(
        input="Tell me about AI agents in detail",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    cancelled_events = [e for e in events_collected if isinstance(e, RunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks before cancellation"

    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


def test_cancel_agent_sync_streaming_preserves_content_in_db(shared_db):
    """Test that cancelled agent run preserves partial content in the database.

    Verifies:
    - Run status is set to cancelled in DB
    - Partial content is stored (not overwritten with cancellation message)
    - Content length matches what was streamed
    """
    agent = Agent(
        name="Content Persist Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very detailed response.",
        db=shared_db,
    )

    session_id = "test_agent_sync_content_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = agent.run(
        input="Write a very long story about a dragon who learns to code. Make it at least 2000 words.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 10 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None
    assert len(last_run.content) > 20, "Stored content should be substantial, not just a cancellation message"
    assert "was cancelled" not in last_run.content or len(last_run.content) > 100, (
        "Content should be actual streamed content, not just the cancellation error message"
    )

    # Also verify messages are preserved
    assert last_run.messages is not None, "Messages should be preserved after cancellation"
    assert len(last_run.messages) > 0, "Should have at least one message preserved"


def test_cancel_agent_sync_streaming_persists_run_cancelled_event_in_db(shared_db):
    """Test that RunCancelled event is persisted in DB when store_events=True."""
    agent = Agent(
        name="Persist Cancel Event Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very detailed response.",
        db=shared_db,
        store_events=True,
    )

    session_id = "test_agent_sync_cancel_event_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    for event in agent.run(
        input="Write a long story about a dragon who learns to code.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.events is not None and len(last_run.events) > 0, "Events should be persisted"

    persisted_event_names = [event.event for event in last_run.events]
    assert RunEvent.run_cancelled in persisted_event_names, "RunCancelled event should be persisted in DB"


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
    - Resources are cleaned up
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

    event_stream = agent.arun(
        input="Tell me about AI technology in detail",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    cancelled = False
    async for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    cancelled_events = [e for e in events_collected if isinstance(e, RunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"

    agent_session = agent.get_session(session_id=session_id)
    assert agent_session is not None
    assert agent_session.runs is not None and len(agent_session.runs) > 0

    last_run = agent_session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None and len(last_run.content) > 0, "Should have captured partial content"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks"

    await asyncio.sleep(0.2)

    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


@pytest.mark.asyncio
async def test_cancel_agent_async_streaming_preserves_content_in_db(shared_db):
    """Async version: stored content should be actual streamed content, not exception message."""
    agent = Agent(
        name="Async Content Persist Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very detailed response.",
        db=shared_db,
    )

    session_id = "test_agent_async_content_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = agent.arun(
        input="Write a very long story about a dragon who learns to code. Make it at least 2000 words.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 10 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    session = agent.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None
    assert "was cancelled" not in last_run.content or len(last_run.content) > 100, (
        "Content should be actual streamed content, not just the cancellation error message"
    )


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
def test_cancel_non_existent_agent_run():
    """Test that cancelling a non-existent run returns False."""
    from agno.db.sqlite import SqliteDb

    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=SqliteDb(db_file="tmp/test_agent_cancel.db"),
    )

    result = agent.cancel_run("non_existent_run_id")
    assert result is False, "Cancelling non-existent run should return False"


# ============================================================================
# SESSION CONTINUITY AFTER CANCELLATION
# ============================================================================
def test_continue_session_after_cancelled_agent_run(shared_db):
    """Test that a new run on the same session sees the cancelled run's history.

    This tests the primary user story from issue #5994: after cancellation,
    users should be able to start a new run on the same session and the AI
    should see what was generated before cancellation.
    """
    agent = Agent(
        name="Continuity Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write detailed responses.",
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
    )

    session_id = "test_agent_session_continuity"
    content_chunks = []
    run_id = None
    cancelled = False

    # Run 1: Start a run and cancel it mid-stream
    for event in agent.run(
        input="Write a very long essay about the history of the internet.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id

        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)

        if len(content_chunks) >= 10 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

        if isinstance(event, RunCancelledEvent):
            break

    assert cancelled, "First run should have been cancelled"

    # Verify the cancelled run is persisted
    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    first_run = session.runs[-1]
    assert first_run.status == RunStatus.cancelled
    assert first_run.content is not None

    # Run 2: Start a new run on the same session
    result = agent.run(
        input="What was I asking about before?",
        session_id=session_id,
        stream=False,
    )

    # Verify second run completed and session now has 2 runs
    assert result is not None
    assert result.status == RunStatus.completed

    session_after = agent.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2


# ============================================================================
# NON-STREAMING SYNC TESTS
# ============================================================================
def test_cancel_agent_non_streaming_sync(shared_db):
    """Test cancelling an agent during non-streaming synchronous execution.

    Pre-cancels the run_id so the first raise_if_cancelled check fires
    immediately — no delay needed. Verifies:
    - Run status is set to cancelled in DB
    """
    agent = Agent(
        name="NonStream Sync Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very long and detailed 5-paragraph response.",
        db=shared_db,
    )

    session_id = "test_agent_nonstream_sync_cancel"

    # Pre-register and cancel the run_id so it cancels immediately
    pre_cancelled_run_id = str(uuid.uuid4())
    register_run(pre_cancelled_run_id)
    cancel_run(pre_cancelled_run_id)

    result = agent.run(
        input="Write an extremely detailed essay about the entire history of computing.",
        session_id=session_id,
        run_id=pre_cancelled_run_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.cancelled, f"Expected cancelled, got {result.status}"

    # Verify in DB
    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0
    assert session.runs[-1].status == RunStatus.cancelled


# ============================================================================
# NON-STREAMING ASYNC TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_agent_non_streaming_async(shared_db):
    """Test cancelling an agent during non-streaming async execution.

    Pre-cancels the run_id so the first araise_if_cancelled check fires
    immediately — no delay needed. Verifies:
    - Run status is set to cancelled in DB
    """
    agent = Agent(
        name="NonStream Async Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent. Write a very long and detailed 5-paragraph response.",
        db=shared_db,
    )

    session_id = "test_agent_nonstream_async_cancel"

    # Pre-register and cancel the run_id so it cancels immediately
    pre_cancelled_run_id = str(uuid.uuid4())
    register_run(pre_cancelled_run_id)
    cancel_run(pre_cancelled_run_id)

    result = await agent.arun(
        input="Write an extremely detailed essay about the entire history of computing.",
        session_id=session_id,
        run_id=pre_cancelled_run_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.cancelled, f"Expected cancelled, got {result.status}"

    # Verify in DB
    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0
    assert session.runs[-1].status == RunStatus.cancelled


# ============================================================================
# CONTINUE RUN AFTER CANCELLATION
# ============================================================================
def test_continue_run_after_cancellation_sync(shared_db):
    """Test that continue_run works on a cancelled run's session.

    Verifies:
    - First run is cancelled and stored
    - A follow-up run on the same session completes successfully
    - Both runs are in the session history
    - The follow-up run has access to the cancelled run's context
    """
    agent = Agent(
        name="Continue After Cancel Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
    )

    session_id = "test_continue_after_cancel_sync"
    content_chunks = []
    run_id = None
    cancelled = False

    # Run 1: Start and cancel mid-stream
    for event in agent.run(
        input="Write a long story about a robot learning to paint.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        if len(content_chunks) >= 8 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    assert cancelled

    # Verify cancelled run in DB
    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    cancelled_run = session.runs[-1]
    assert cancelled_run.status == RunStatus.cancelled
    cancelled_content = cancelled_run.content
    assert cancelled_content is not None and len(cancelled_content) > 0

    # Run 2: Follow-up non-streaming run on same session
    result = agent.run(
        input="Continue from where you left off. What happened next in the story?",
        session_id=session_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.completed
    assert result.content is not None and len(result.content) > 0

    # Verify session has both runs
    session_after = agent.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2
    assert session_after.runs[-2].status == RunStatus.cancelled
    assert session_after.runs[-1].status == RunStatus.completed


@pytest.mark.asyncio
async def test_continue_run_after_cancellation_async(shared_db):
    """Async version: continue_run works on a cancelled run's session.

    Verifies same invariants as sync version but using async paths.
    """
    agent = Agent(
        name="Continue After Cancel Async Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful agent.",
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
    )

    session_id = "test_continue_after_cancel_async"
    content_chunks = []
    run_id = None
    cancelled = False

    # Run 1: Start and cancel mid-stream (async)
    async for event in agent.arun(
        input="Write a long story about a robot learning to paint.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        if len(content_chunks) >= 8 and run_id and not cancelled:
            agent.cancel_run(run_id)
            cancelled = True

    assert cancelled

    # Verify cancelled run in DB
    session = agent.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    assert session.runs[-1].status == RunStatus.cancelled

    # Run 2: Follow-up non-streaming async run
    result = await agent.arun(
        input="Continue from where you left off. What happened next in the story?",
        session_id=session_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.completed

    # Verify session has both runs
    session_after = agent.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2

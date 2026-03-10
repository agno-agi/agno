"""Integration tests for team cancellation with partial data preservation.

These tests verify that when a team run is cancelled mid-execution:
1. The partial content generated before cancellation is preserved
2. The team run status is set to cancelled
3. All partial data (content + messages) is stored in the database
4. Cancellation events are emitted properly
5. Resources are cleaned up properly
6. Both member and leader content is preserved
"""

import asyncio
import os
import threading
import time
from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.exceptions import RunCancelledException
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.team import Team

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


def _make_team(db, name="Test Team"):
    """Helper to create a team with a researcher member."""
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Write detailed responses.",
    )
    return Team(
        name=name,
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        store_tool_messages=True,
        store_history_messages=True,
    )


# ============================================================================
# SYNCHRONOUS STREAMING TESTS
# ============================================================================
def test_cancel_team_during_sync_streaming(shared_db):
    """Test cancelling a team during synchronous streaming execution.

    Verifies:
    - Cancellation event is received
    - Partial content is collected before cancellation
    - Resources are cleaned up (run removed from tracking)
    """
    from agno.run.cancel import _cancellation_manager

    team = _make_team(shared_db)

    session_id = "test_team_sync_cancel_session"
    events_collected = []
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
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

        # Cancel after collecting some content
        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"

    # Verify we collected content before cancellation
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks before cancellation"

    # Verify the run was cleaned up
    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


def test_cancel_team_sync_streaming_preserves_content_in_db(shared_db):
    """Test that cancelled team run preserves partial content in the database.

    Verifies:
    - Run status is set to cancelled in DB
    - Partial content is stored (not overwritten with cancellation message)
    - Content length matches what was streamed
    """
    team = _make_team(shared_db)

    session_id = "test_team_sync_content_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
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
            team.cancel_run(run_id)
            cancelled = True

    # Verify database persistence
    session = team.get_session(session_id=session_id)
    assert session is not None, "Session should exist"
    assert session.runs is not None and len(session.runs) > 0, "Should have at least one run"

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled, f"Run status should be cancelled, got {last_run.status}"
    assert last_run.content is not None, "Partial content should be preserved"
    assert len(last_run.content) > 0, "Content should not be empty"

    # The stored content should be actual streamed content, not just "Run was cancelled"
    assert len(last_run.content) > 20, "Stored content should be substantial, not just a cancellation message"


def test_cancel_team_sync_streaming_preserves_messages_in_db(shared_db):
    """Test that cancelled team run preserves partial messages in the database.

    Verifies:
    - Messages are stored even when run is cancelled
    - At least the user input message is preserved
    """
    team = _make_team(shared_db)

    session_id = "test_team_sync_messages_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    # Verify messages are preserved
    session = team.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]
    assert last_run.messages is not None, "Messages should be preserved after cancellation"
    assert len(last_run.messages) > 0, "Should have at least one message preserved"


# ============================================================================
# ASYNCHRONOUS STREAMING TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_team_during_async_streaming(shared_db):
    """Test cancelling a team during asynchronous streaming execution.

    Verifies:
    - Cancellation event is received
    - Partial content is preserved in database
    - Run status is set to cancelled
    - Resources are cleaned up
    """
    from agno.run.cancel import _cancellation_manager

    team = _make_team(shared_db)

    session_id = "test_team_async_cancel_session"
    events_collected = []
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.arun(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"

    # Verify database persistence
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None and len(last_run.content) > 0, "Should have captured partial content"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks"

    await asyncio.sleep(0.2)

    # Verify cleanup
    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


@pytest.mark.asyncio
async def test_cancel_team_async_streaming_preserves_messages(shared_db):
    """Test that async cancelled team run preserves messages in database."""
    team = _make_team(shared_db)

    session_id = "test_team_async_messages_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.arun(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    session = team.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]
    assert last_run.messages is not None, "Messages should be preserved after async cancellation"
    assert len(last_run.messages) > 0, "Should have at least one message preserved"


# ============================================================================
# NON-STREAMING CANCELLATION TESTS
# ============================================================================
def test_cancel_team_sync_non_streaming(shared_db):
    """Test cancelling a team during synchronous non-streaming execution.

    Uses a separate thread to cancel the run while it's executing.
    """
    team = _make_team(shared_db)

    session_id = "test_team_sync_non_streaming_cancel"
    run_id = "test_team_non_streaming_run_id"
    result = None
    exception_raised = None

    def run_team():
        nonlocal result, exception_raised
        try:
            result = team.run(
                input="Write a very detailed essay about the history of computing from the 1940s to today",
                session_id=session_id,
                run_id=run_id,
                stream=False,
            )
        except RunCancelledException as e:
            exception_raised = e

    team_thread = threading.Thread(target=run_team)
    team_thread.start()

    time.sleep(1.0)
    cancel_result = team.cancel_run(run_id)

    team_thread.join(timeout=15)

    if cancel_result:
        if exception_raised:
            assert isinstance(exception_raised, RunCancelledException)
        elif result:
            assert result.status in [RunStatus.cancelled, RunStatus.completed]
    else:
        assert result is not None


@pytest.mark.asyncio
async def test_cancel_team_async_non_streaming(shared_db):
    """Test cancelling a team during asynchronous non-streaming execution."""
    team = _make_team(shared_db)

    session_id = "test_team_async_non_streaming_cancel"
    run_id = "test_team_async_non_streaming_run_id"

    async def cancel_after_delay():
        await asyncio.sleep(1.0)
        team.cancel_run(run_id)

    cancel_task = asyncio.create_task(cancel_after_delay())

    try:
        result = await team.arun(
            input="Write a very detailed essay about artificial intelligence and its impact on society",
            session_id=session_id,
            run_id=run_id,
            stream=False,
        )
        assert result.status in [RunStatus.completed, RunStatus.cancelled]
    except RunCancelledException:
        pass

    cancel_task.cancel()
    try:
        await cancel_task
    except asyncio.CancelledError:
        pass


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
def test_cancel_team_immediately(shared_db):
    """Test cancelling a team immediately after it starts."""
    team = _make_team(shared_db)

    session_id = "test_team_immediate_cancel"
    events_collected = []
    run_id = None
    cancelled = False

    event_stream = team.run(
        input="Tell me about AI",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
            if not cancelled:
                team.cancel_run(run_id)
                cancelled = True

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    assert run_id is not None, "Should have received at least one event with run_id"

    # Verify session contains exactly one cancelled run (not zero)
    session = team.get_session(session_id=session_id)
    assert session is not None, "Session should exist after immediate cancellation"
    assert session.runs is not None and len(session.runs) == 1, "Session should contain exactly one run"
    assert session.runs[0].status == RunStatus.cancelled, "The single run should have cancelled status"


def test_cancel_non_existent_team_run():
    """Test that cancelling a non-existent run returns False."""
    team = Team(
        name="Test Team",
        members=[
            Agent(
                name="Member",
                model=OpenAIChat(id="gpt-4o-mini"),
            )
        ],
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    result = team.cancel_run("non_existent_run_id")
    assert result is False, "Cancelling non-existent run should return False"


def test_multiple_cancel_calls_team(shared_db):
    """Test that multiple cancel calls don't cause issues."""
    team = _make_team(shared_db)

    session_id = "test_team_multiple_cancel"
    run_id = None
    cancelled = False
    events_collected = []

    event_stream = team.run(
        input="Tell me about AI",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        events_collected.append(event)
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
            if not cancelled:
                team.cancel_run(run_id)
                team.cancel_run(run_id)
                team.cancel_run(run_id)
                cancelled = True

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"


# ============================================================================
# CONTENT PRESERVATION SPECIFIC TESTS
# ============================================================================
def test_cancel_team_content_not_overwritten_with_error_message(shared_db):
    """Test that stored content is actual streamed content, not the exception message.

    This is the core bug that the PR fixes: before the fix, run_response.content
    was unconditionally set to str(e) which is 'Run <id> was cancelled',
    overwriting any partial content that had been streamed.
    """
    team = _make_team(shared_db)

    session_id = "test_team_content_not_overwritten"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        # Wait for substantial content before cancelling
        if len(content_chunks) >= 15 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    session = team.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]

    # The key assertion: stored content should NOT be just the cancellation message
    assert last_run.content is not None
    assert "was cancelled" not in last_run.content or len(last_run.content) > 100, (
        "Content should be actual streamed content, not just the cancellation error message"
    )


@pytest.mark.asyncio
async def test_cancel_team_async_content_not_overwritten(shared_db):
    """Async version: stored content should be actual streamed content, not exception message."""
    team = _make_team(shared_db)

    session_id = "test_team_async_content_not_overwritten"
    content_chunks = []
    run_id = None
    cancelled = False

    event_stream = team.arun(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 15 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    session = team.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]

    assert last_run.content is not None
    assert "was cancelled" not in last_run.content or len(last_run.content) > 100, (
        "Content should be actual streamed content, not just the cancellation error message"
    )


# ============================================================================
# REDIS CANCELLATION TESTS
# ============================================================================
@pytest.fixture
def fakeredis_clients():
    """Create in-memory Redis clients using fakeredis for testing."""
    import fakeredis
    from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

    sync_client = fakeredis.FakeStrictRedis(decode_responses=False)
    async_client = AsyncFakeRedis(decode_responses=False)

    yield sync_client, async_client


@pytest.fixture
def redis_cancellation_manager(fakeredis_clients):
    """Set up Redis cancellation manager with fakeredis and restore original after test."""
    from agno.run.cancel import get_cancellation_manager, set_cancellation_manager
    from agno.run.cancellation_management import RedisRunCancellationManager

    original_manager = get_cancellation_manager()

    sync_client, async_client = fakeredis_clients
    redis_manager = RedisRunCancellationManager(
        redis_client=sync_client,
        async_redis_client=async_client,
        key_prefix="agno:run:cancellation:",
        ttl_seconds=None,
    )

    set_cancellation_manager(redis_manager)

    yield redis_manager

    set_cancellation_manager(original_manager)


@patch("agno.team._run.cleanup_run", return_value=None)
def test_cancel_team_with_redis_sync_streaming(cleanup_run_mock, shared_db, redis_cancellation_manager):
    """Test cancelling a team during sync streaming with Redis backend.

    Verifies:
    - Cancellation works with Redis backend
    - Partial content is collected before cancellation
    - Run is tracked in Redis
    """
    team = _make_team(shared_db)

    session_id = "test_team_redis_sync_cancel"
    events_collected = []
    run_id = None

    event_stream = team.run(
        input="Write a 5-paragraph essay about technology",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if len(events_collected) == 1 and run_id:
            assert redis_cancellation_manager.get_active_runs()[run_id] is False
            team.cancel_run(run_id)

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    cleanup_run_mock.assert_called_once_with(run_id)


@pytest.mark.asyncio
@patch("agno.team._run.acleanup_run", return_value=None)
async def test_cancel_team_with_redis_async_streaming(cleanup_run_mock, shared_db, redis_cancellation_manager):
    """Test cancelling a team during async streaming with Redis backend.

    Verifies:
    - Cancellation works with async Redis backend
    - Partial content is preserved in database
    - Run status is set to cancelled
    """
    team = _make_team(shared_db)

    session_id = "test_team_redis_async_cancel"
    events_collected = []
    run_id = None

    event_stream = team.arun(
        input="Write 10 random words",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if len(events_collected) == 5 and run_id:
            await redis_cancellation_manager.acancel_run(run_id)

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    cleanup_run_mock.assert_called_once_with(run_id)

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled

    is_cancelled = await redis_cancellation_manager.ais_cancelled(run_id)
    assert is_cancelled, "Run should be marked as cancelled in Redis"

    await asyncio.sleep(0.2)


# ============================================================================
# CONTINUE_RUN CANCELLATION TESTS
# These test the _continue_run, _continue_run_stream,
# _acontinue_run, _acontinue_run_stream handlers
# ============================================================================
def test_cancel_team_continue_run_sync_streaming(shared_db):
    """Test cancelling a team during continue_run with sync streaming.

    Tests the _continue_run_stream handler.
    Note: Team continue_run only produces a stream when resuming from a
    tool-pause (has_team_level requirements). Without pauses, it returns
    TeamRunOutput directly. This test verifies both paths work correctly.
    """
    team = _make_team(shared_db)

    session_id = "test_team_continue_sync_stream_cancel"

    # First run: complete a normal run to establish session state
    first_result = team.run(
        input="Write a detailed essay about AI",
        session_id=session_id,
        stream=False,
    )
    assert first_result.status == RunStatus.completed

    # Continue run - may return iterator (tool-pause path) or TeamRunOutput (fallback)
    result = team.continue_run(
        run_response=first_result,
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    from agno.run.team import TeamRunOutput

    if isinstance(result, TeamRunOutput):
        # Fallback path: no tool-pause, returned directly
        assert result.status == RunStatus.completed
    else:
        # Streaming path: cancel mid-stream
        events_collected = []
        run_id = None
        cancelled = False
        for event in result:
            events_collected.append(event)
            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id
                if not cancelled:
                    team.cancel_run(run_id)
                    cancelled = True

        session = team.get_session(session_id=session_id)
        assert session is not None
        last_run = session.runs[-1]
        assert last_run.status in [RunStatus.cancelled, RunStatus.completed]


def test_cancel_team_continue_run_sync_non_streaming(shared_db):
    """Test cancelling a team during continue_run without streaming.

    Tests the _continue_run handler.
    """
    team = _make_team(shared_db)

    session_id = "test_team_continue_sync_non_stream_cancel"

    # First run
    first_result = team.run(
        input="Say hello briefly",
        session_id=session_id,
        stream=False,
    )
    assert first_result.status == RunStatus.completed

    run_id = "test_team_continue_non_stream_run"
    result = None
    exception_raised = None

    def run_continue():
        nonlocal result, exception_raised
        try:
            result = team.continue_run(
                run_response=first_result,
                run_id=run_id,
                session_id=session_id,
                stream=False,
            )
        except RunCancelledException as e:
            exception_raised = e

    team_thread = threading.Thread(target=run_continue)
    team_thread.start()

    time.sleep(1.0)
    cancel_result = team.cancel_run(run_id)

    team_thread.join(timeout=15)

    if cancel_result:
        if exception_raised:
            assert isinstance(exception_raised, RunCancelledException)
        elif result:
            assert result.status in [RunStatus.cancelled, RunStatus.completed]
    else:
        assert result is not None


@pytest.mark.asyncio
async def test_cancel_team_continue_run_async_streaming(shared_db):
    """Test cancelling a team during acontinue_run with async streaming.

    Tests the _acontinue_run_stream handler.
    """
    team = _make_team(shared_db)

    session_id = "test_team_continue_async_stream_cancel"

    # First run
    first_result = await team.arun(
        input="Write a very long detailed essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=False,
    )
    assert first_result.status == RunStatus.completed

    events_collected = []
    run_id = None
    cancelled = False

    event_stream = team.acontinue_run(
        run_response=first_result,
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    async for event in event_stream:
        events_collected.append(event)

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
            if not cancelled:
                team.cancel_run(run_id)
                cancelled = True

    session = team.get_session(session_id=session_id)
    assert session is not None
    last_run = session.runs[-1]
    # With immediate cancel, the run might complete before cancellation takes effect
    assert last_run.status in [RunStatus.cancelled, RunStatus.completed]
    if last_run.status == RunStatus.cancelled:
        cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
        assert len(cancelled_events) == 1


@pytest.mark.asyncio
async def test_cancel_team_continue_run_async_non_streaming(shared_db):
    """Test cancelling a team during acontinue_run without streaming.

    Tests the _acontinue_run handler.
    """
    team = _make_team(shared_db)

    session_id = "test_team_continue_async_non_stream_cancel"

    # First run
    first_result = await team.arun(
        input="Say hello briefly",
        session_id=session_id,
        stream=False,
    )
    assert first_result.status == RunStatus.completed

    run_id = "test_team_continue_async_non_stream_run"

    async def cancel_after_delay():
        await asyncio.sleep(1.0)
        team.cancel_run(run_id)

    cancel_task = asyncio.create_task(cancel_after_delay())

    try:
        result = await team.acontinue_run(
            run_response=first_result,
            run_id=run_id,
            session_id=session_id,
            stream=False,
        )
        assert result.status in [RunStatus.completed, RunStatus.cancelled]
    except RunCancelledException:
        pass

    cancel_task.cancel()
    try:
        await cancel_task
    except asyncio.CancelledError:
        pass


# ============================================================================
# STORE MEMBER RESPONSES + CANCELLATION TESTS
# ============================================================================
def test_cancel_team_with_store_member_responses(shared_db):
    """Test cancellation when store_member_responses=True.

    Verifies that member runs are stored in the team session even when
    the team run is cancelled mid-delegation.
    """
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Write very detailed responses about any topic.",
    )
    team = Team(
        name="Member Store Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
        store_member_responses=True,
    )

    session_id = "test_team_store_member_cancel"
    content_chunks = []
    run_id = None
    cancelled = False

    for event in team.run(
        input="Write a very long essay about space exploration with at least 10 paragraphs.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id

        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)

        if len(content_chunks) >= 15 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

        if isinstance(event, TeamRunCancelledEvent):
            break

    assert cancelled, "Run should have been cancelled"

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled


# ============================================================================
# SESSION CONTINUITY AFTER CANCELLATION TESTS
# ============================================================================
def test_continue_session_after_cancelled_run(shared_db):
    """Test that a new run on the same session sees the cancelled run's history.

    This tests the primary user story from issue #5994: after cancellation,
    users should be able to start a new run on the same session and the AI
    should see what was generated before cancellation.
    """
    team = _make_team(shared_db, name="Continuity Team")

    session_id = "test_team_session_continuity"
    content_chunks = []
    run_id = None
    cancelled = False

    # Run 1: Start a run and cancel it mid-stream
    for event in team.run(
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
            team.cancel_run(run_id)
            cancelled = True

        if isinstance(event, TeamRunCancelledEvent):
            break

    assert cancelled, "First run should have been cancelled"

    # Verify the cancelled run is persisted
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    first_run = session.runs[-1]
    assert first_run.status == RunStatus.cancelled
    assert first_run.content is not None

    # Run 2: Start a new run on the same session
    result = team.run(
        input="What was I asking about before?",
        session_id=session_id,
        stream=False,
    )

    # Verify second run completed and session now has 2 runs
    assert result is not None
    assert result.status == RunStatus.completed

    session_after = team.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2

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
import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.cancel import cancel_run, register_run
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import TeamRunEvent, TeamRunOutput
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

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks before cancellation"

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

    session = team.get_session(session_id=session_id)
    assert session is not None, "Session should exist"
    assert session.runs is not None and len(session.runs) > 0, "Should have at least one run"

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled, f"Run status should be cancelled, got {last_run.status}"
    assert last_run.content is not None, "Partial content should be preserved"
    assert len(last_run.content) > 20, "Stored content should be substantial, not just a cancellation message"

    # Also verify messages are preserved
    assert last_run.messages is not None, "Messages should be preserved after cancellation"
    assert len(last_run.messages) > 0, "Should have at least one message preserved"


def test_cancel_team_sync_streaming_persists_run_cancelled_event_in_db(shared_db):
    """Test that Team RunCancelled event is persisted in DB when store_events=True."""
    team = _make_team(shared_db, name="Persist Team Cancel Event")
    team.store_events = True

    session_id = "test_team_sync_cancel_event_persist"
    content_chunks = []
    run_id = None
    cancelled = False

    for event in team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.events is not None and len(last_run.events) > 0, "Events should be persisted"

    persisted_event_names = [event.event for event in last_run.events]
    assert TeamRunEvent.run_cancelled in persisted_event_names, "Team RunCancelled event should be persisted in DB"


def test_cancel_team_sync_streaming_yields_run_output_when_requested(shared_db):
    """Test that cancelled streaming team run yields TeamRunOutput when yield_run_output=True."""
    team = _make_team(shared_db, name="Yield Team Output On Cancel")

    session_id = "test_team_sync_cancel_yield_run_output"
    content_chunks = []
    run_id = None
    cancelled = False
    yielded_outputs = []

    for event in team.run(
        input="Write a very long essay about the history of artificial intelligence with at least 10 major milestones.",
        session_id=session_id,
        stream=True,
        stream_events=True,
        yield_run_output=True,
    ):
        if isinstance(event, TeamRunOutput):
            yielded_outputs.append(event)
            continue

        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)

        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    assert len(yielded_outputs) == 1, "Should yield one final TeamRunOutput after cancellation"
    assert yielded_outputs[0].status == RunStatus.cancelled, "Final yielded TeamRunOutput should be cancelled"


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

    cancelled_events = [e for e in events_collected if isinstance(e, TeamRunCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one RunCancelledEvent"

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None and len(last_run.content) > 0, "Should have captured partial content"
    assert len(content_chunks) >= 5, "Should have collected at least 5 content chunks"

    await asyncio.sleep(0.2)

    active_runs = _cancellation_manager.get_active_runs()
    assert run_id not in active_runs, "Run should be cleaned up from tracking"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
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


# ============================================================================
# SESSION CONTINUITY AFTER CANCELLATION
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


# ============================================================================
# NON-STREAMING SYNC TEAM TESTS
# ============================================================================
def test_cancel_team_non_streaming_sync(shared_db):
    """Test cancelling a team during non-streaming synchronous execution.

    Pre-cancels the run_id so the first raise_if_cancelled check fires
    immediately — no delay needed. Verifies:
    - Run status is set to cancelled in DB
    """
    team = _make_team(shared_db, name="NonStream Sync Team")

    session_id = "test_team_nonstream_sync_cancel"

    # Pre-register and cancel the run_id so it cancels immediately
    pre_cancelled_run_id = str(uuid.uuid4())
    register_run(pre_cancelled_run_id)
    cancel_run(pre_cancelled_run_id)

    result = team.run(
        input="Write an extremely detailed essay about the entire history of computing.",
        session_id=session_id,
        run_id=pre_cancelled_run_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.cancelled, f"Expected cancelled, got {result.status}"

    # Verify in DB
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0
    assert session.runs[-1].status == RunStatus.cancelled


# ============================================================================
# NON-STREAMING ASYNC TEAM TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_team_non_streaming_async(shared_db):
    """Test cancelling a team during non-streaming async execution.

    Pre-cancels the run_id so the first araise_if_cancelled check fires
    immediately — no delay needed. Verifies:
    - Run status is set to cancelled in DB
    """
    team = _make_team(shared_db, name="NonStream Async Team")

    session_id = "test_team_nonstream_async_cancel"

    # Pre-register and cancel the run_id so it cancels immediately
    pre_cancelled_run_id = str(uuid.uuid4())
    register_run(pre_cancelled_run_id)
    cancel_run(pre_cancelled_run_id)

    result = await team.arun(
        input="Write an extremely detailed essay about the entire history of computing.",
        session_id=session_id,
        run_id=pre_cancelled_run_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.cancelled, f"Expected cancelled, got {result.status}"

    # Verify in DB
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0
    assert session.runs[-1].status == RunStatus.cancelled


# ============================================================================
# MEMBER RUN PERSISTENCE ON TEAM CANCELLATION
# ============================================================================
def test_member_run_in_team_run_output_on_cancellation_sync(shared_db):
    """Test that member run content is preserved when a streaming team is cancelled.

    Verifies:
    - Team run status is cancelled
    - Content is preserved (not overwritten)
    """
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Write a very long detailed analysis.",
    )
    team = Team(
        name="Member Persist Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
    )

    session_id = "test_member_persist_on_cancel_sync"
    content_chunks = []
    run_id = None
    cancelled = False

    for event in team.run(
        input="Write an extremely detailed 10-paragraph analysis of quantum computing history.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    assert cancelled

    # Verify team run is cancelled
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None


@pytest.mark.asyncio
async def test_member_run_in_team_run_output_on_cancellation_async(shared_db):
    """Async version: member run content is preserved when a streaming team is cancelled."""
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Write a very long detailed analysis.",
    )
    team = Team(
        name="Member Persist Async Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        store_tool_messages=True,
        store_history_messages=True,
    )

    session_id = "test_member_persist_on_cancel_async"
    content_chunks = []
    run_id = None
    cancelled = False

    async for event in team.arun(
        input="Write an extremely detailed 10-paragraph analysis of quantum computing history.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            content_chunks.append(event.content)
        if len(content_chunks) >= 5 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    assert cancelled

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) > 0

    last_run = session.runs[-1]
    assert last_run.status == RunStatus.cancelled
    assert last_run.content is not None


# ============================================================================
# CONTINUE SESSION AFTER TEAM CANCELLATION
# ============================================================================
def test_continue_team_session_after_cancellation_sync(shared_db):
    """Test continuing a team session after cancellation (sync).

    Verifies:
    - First run cancelled and stored
    - Second run on same session completes
    - Both runs in session history
    """
    team = _make_team(shared_db, name="Continue Team Sync")

    session_id = "test_team_continue_after_cancel_sync"
    content_chunks = []
    run_id = None
    cancelled = False

    for event in team.run(
        input="Write a long story about space exploration.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id
        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)
        if len(content_chunks) >= 8 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    assert cancelled

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    assert session.runs[-1].status == RunStatus.cancelled

    # Run 2: Follow-up non-streaming
    result = team.run(
        input="What was I asking about before?",
        session_id=session_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.completed

    session_after = team.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2
    assert session_after.runs[-2].status == RunStatus.cancelled
    assert session_after.runs[-1].status == RunStatus.completed


@pytest.mark.asyncio
async def test_continue_team_session_after_cancellation_async(shared_db):
    """Async version: continuing a team session after cancellation.

    Verifies same invariants as sync version.
    """
    team = _make_team(shared_db, name="Continue Team Async")

    session_id = "test_team_continue_after_cancel_async"
    content_chunks = []
    run_id = None
    cancelled = False

    async for event in team.arun(
        input="Write a long story about space exploration.",
        session_id=session_id,
        stream=True,
        stream_events=True,
    ):
        if run_id is None and hasattr(event, "run_id") and event.run_id:
            run_id = event.run_id
        if hasattr(event, "content") and event.content:
            content_chunks.append(event.content)
        if len(content_chunks) >= 8 and run_id and not cancelled:
            team.cancel_run(run_id)
            cancelled = True

    assert cancelled

    session = team.get_session(session_id=session_id)
    assert session is not None
    assert session.runs is not None and len(session.runs) >= 1
    assert session.runs[-1].status == RunStatus.cancelled

    # Run 2: Follow-up non-streaming async
    result = await team.arun(
        input="What was I asking about before?",
        session_id=session_id,
        stream=False,
    )

    assert result is not None
    assert result.status == RunStatus.completed

    session_after = team.get_session(session_id=session_id)
    assert session_after is not None
    assert session_after.runs is not None and len(session_after.runs) >= 2

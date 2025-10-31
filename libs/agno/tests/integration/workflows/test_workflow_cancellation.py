import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCancelledEvent
from agno.workflow import Step, Workflow
from agno.workflow.types import StepOutput


# Test fixtures
@pytest.fixture
def streaming_workflow_with_agents(shared_db):
    """Create a workflow with agent steps for cancellation testing."""
    agent1 = Agent(
        name="Fast Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a fast agent. Respond with exactly: 'Fast response from agent 1'",
    )

    agent2 = Agent(
        name="Streaming Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a streaming agent. Write a detailed response about AI agents in 2025.",
    )

    agent3 = Agent(
        name="Final Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are the final agent. This should never execute.",
    )

    return Workflow(
        name="Agent Cancellation Test Workflow",
        db=shared_db,
        steps=[
            Step(name="agent_step_1", agent=agent1),
            Step(name="agent_step_2", agent=agent2),
            Step(name="agent_step_3", agent=agent3),
        ],
    )


# ============================================================================
# SYNCHRONOUS STREAMING TESTS
# ============================================================================
def test_cancel_workflow_with_agents_during_streaming(streaming_workflow_with_agents):
    """Test cancelling a workflow with agent steps during streaming (synchronous)."""
    workflow = streaming_workflow_with_agents
    session_id = "test_sync_agent_cancel_session"

    events_collected = []
    content_from_agent_2 = []
    run_id = None

    # Start streaming workflow
    event_stream = workflow.run(
        input="Tell me about AI agents in 2025",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    # Collect events and cancel during agent 2's streaming
    for event in event_stream:
        events_collected.append(event)

        # Extract run_id from the first event
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        # Track content from agent 2
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            # Check if we're in agent_step_2 context
            if hasattr(event, "step_name") and event.step_name == "agent_step_2":
                content_from_agent_2.append(event.content)

        # Cancel after collecting some content from agent 2
        # We need to wait for agent 1 to complete and agent 2 to start streaming
        if len(content_from_agent_2) >= 5 and run_id:  # Wait for a few chunks from agent 2
            workflow.cancel_run(run_id)
            # Continue collecting remaining events
            try:
                for remaining_event in event_stream:
                    events_collected.append(remaining_event)
            except StopIteration:
                pass
            break

    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one WorkflowCancelledEvent"

    # Verify the workflow run was saved with partial data
    workflow_session = workflow.get_session(session_id=session_id)
    assert workflow_session is not None
    assert workflow_session.runs is not None and len(workflow_session.runs) > 0

    last_run = workflow_session.runs[-1]
    assert last_run.status == RunStatus.cancelled

    # Verify we have both completed agent 1 and partial agent 2
    assert last_run.step_results is not None
    assert len(last_run.step_results) >= 2, "Should have at least 2 steps saved"

    # Verify agent 1 completed
    step_1_result = last_run.step_results[0]
    assert step_1_result.step_name == "agent_step_1"
    assert step_1_result.content is not None and len(step_1_result.content) > 0

    # Verify agent 2 has partial content
    step_2_result = last_run.step_results[1]
    assert step_2_result.step_name == "agent_step_2"
    assert step_2_result.content is not None and len(step_2_result.content) > 0, (
        "Agent 2 should have captured partial content"
    )
    assert step_2_result.success is False
    assert "Cancelled during execution" in (step_2_result.error or "")


# ============================================================================
# ASYNCHRONOUS STREAMING TESTS
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_workflow_with_agents_during_async_streaming(streaming_workflow_with_agents):
    """Test cancelling a workflow with agent steps during async streaming."""
    workflow = streaming_workflow_with_agents
    session_id = "test_async_agent_cancel_session"

    events_collected = []
    content_from_agent_2 = []
    run_id = None

    # Start async streaming workflow
    event_stream = workflow.arun(
        input="Tell me about AI agents in 2025",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    # Collect events and cancel during agent 2's streaming
    async for event in event_stream:
        events_collected.append(event)

        # Extract run_id from the first event
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        # Track content from agent 2
        if hasattr(event, "content") and event.content and isinstance(event.content, str):
            if hasattr(event, "step_name") and event.step_name == "agent_step_2":
                content_from_agent_2.append(event.content)

        # Cancel after collecting some content from agent 2
        if len(content_from_agent_2) >= 5 and run_id:
            workflow.cancel_run(run_id)
            # Continue collecting remaining events
            try:
                async for remaining_event in event_stream:
                    events_collected.append(remaining_event)
            except StopAsyncIteration:
                pass
            break

    # Verify cancellation event was received
    cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
    assert len(cancelled_events) == 1, "Should have exactly one WorkflowCancelledEvent"

    # Verify the workflow run was saved with partial data
    # Use sync method since shared_db is SqliteDb (synchronous)
    workflow_session = workflow.get_session(session_id=session_id)
    assert workflow_session is not None
    assert workflow_session.runs is not None and len(workflow_session.runs) > 0

    last_run = workflow_session.runs[-1]
    assert last_run.status == RunStatus.cancelled

    # Verify we have both completed agent 1 and partial agent 2
    assert last_run.step_results is not None
    assert len(last_run.step_results) >= 2, "Should have at least 2 steps saved"

    # Verify agent 1 completed
    step_1_result = last_run.step_results[0]
    assert step_1_result.step_name == "agent_step_1"
    assert step_1_result.content is not None and len(step_1_result.content) > 0

    # Verify agent 2 has partial content
    step_2_result = last_run.step_results[1]
    assert step_2_result.step_name == "agent_step_2"
    assert step_2_result.content is not None and len(step_2_result.content) > 0, (
        "Agent 2 should have captured partial content"
    )
    assert step_2_result.success is False
    assert "Cancelled during execution" in (step_2_result.error or "")


# ============================================================================
# EDGE CASE TESTS
# ============================================================================
def test_cancel_workflow_before_step_2_starts(streaming_workflow_with_agents):
    """Test cancelling a workflow after step 1 completes but before step 2 starts."""
    workflow = streaming_workflow_with_agents
    session_id = "test_cancel_between_steps"

    events_collected = []
    step_1_completed = False
    run_id = None

    event_stream = workflow.run(
        input="test cancellation timing",
        session_id=session_id,
        stream=True,
        stream_events=True,
    )

    for event in event_stream:
        events_collected.append(event)

        # Extract run_id from the first event
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id

        # Check if step 1 just completed
        if hasattr(event, "step_name") and event.step_name == "agent_step_1" and hasattr(event, "content"):
            if isinstance(event.content, str) and len(event.content) > 0:
                step_1_completed = True
                # Cancel immediately after step 1 completes
                if run_id:
                    workflow.cancel_run(run_id)
                # Continue collecting remaining events
                try:
                    for remaining_event in event_stream:
                        events_collected.append(remaining_event)
                except StopIteration:
                    pass
                break

    assert step_1_completed, "Step 1 should have completed"

    # Verify the workflow was cancelled
    cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
    assert len(cancelled_events) == 1

    # Verify database state
    workflow_session = workflow.get_session(session_id=session_id)
    last_run = workflow_session.runs[-1]

    assert last_run.status == RunStatus.cancelled
    assert last_run.step_results is not None
    # Should only have step 1 since we cancelled before step 2 started
    assert len(last_run.step_results) == 1, "Should only have step 1 result"
    assert last_run.step_results[0].step_name == "agent_step_1"


@pytest.mark.asyncio
async def test_cancel_non_existent_run():
    """Test that cancelling a non-existent run returns False."""
    from agno.db.sqlite import SqliteDb

    workflow = Workflow(
        name="Test Workflow",
        db=SqliteDb(db_file="tmp/test_cancel.db"),
        steps=[Step(name="test_step", executor=lambda si: StepOutput(content="test"))],
    )

    # Try to cancel a run that doesn't exist
    result = workflow.cancel_run("non_existent_run_id")
    assert result is False, "Cancelling non-existent run should return False"

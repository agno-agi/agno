import asyncio
import threading
import time
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus
from agno.run.cancel import cancel_run
from agno.run.workflow import WorkflowCancelledEvent
from agno.workflow import Step, Workflow
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput

# ============================================================================
# FIXTURES
# ============================================================================


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
# FUNCTION EXECUTOR HELPERS (no LLM needed)
# ============================================================================


def sync_streaming_executor(step_input: StepInput) -> Iterator[Any]:
    """Sync generator that yields numbered content events."""
    for i in range(10):
        time.sleep(0.05)
        yield RunContentEvent(content=str(i))


async def async_streaming_executor(step_input: StepInput) -> AsyncIterator[Any]:
    """Async generator that yields numbered content events."""
    for i in range(10):
        await asyncio.sleep(0.05)
        yield RunContentEvent(content=str(i))


def sync_passthrough_executor(step_input: StepInput) -> StepOutput:
    return StepOutput(content="passthrough")


async def async_passthrough_executor(step_input: StepInput) -> StepOutput:
    return StepOutput(content="passthrough")


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
    assert "cancelled" in (step_2_result.error or "").lower()


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
    assert "cancelled" in (step_2_result.error or "").lower()


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
    # Should have step 1 results (may include both skipped and partial progress entries)
    assert len(last_run.step_results) >= 1, "Should have at least step 1 result"
    # All step results should be for agent_step_1 (step 2 should not have started)
    for step_result in last_run.step_results:
        assert step_result.step_name == "agent_step_1", "Only step 1 should have results"


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


# ============================================================================
# SINGLE-STEP CANCELLATION TESTS (regression for #7718)
#
# When cancelling a single-step workflow mid-stream, partial content was lost
# because RunCancelledException was caught by the inner `except Exception` block
# and swallowed by the default on_error="skip" policy.
# ============================================================================


class TestSingleStepCancellationStreaming:
    """Single-step streaming workflow cancellation must preserve partial content."""

    def test_sync_single_step_cancel_preserves_partial_content(self, shared_db):
        """Cancelling a single-step streaming workflow should save partial content."""
        workflow = Workflow(
            name="Single Step Cancel Test",
            db=shared_db,
            steps=[Step(name="streaming_step", executor=sync_streaming_executor)],
            telemetry=False,
        )

        session_id = "sync_single_step_cancel"
        events_collected = []
        run_id = None

        event_stream = workflow.run(
            input="test",
            session_id=session_id,
            stream=True,
            stream_events=True,
        )

        for event in event_stream:
            events_collected.append(event)

            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            # Cancel after receiving content "3"
            if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
                workflow.cancel_run(run_id)
                for remaining in event_stream:
                    events_collected.append(remaining)
                break

        # Should have a WorkflowCancelledEvent
        cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
        assert len(cancelled_events) == 1, "Should emit exactly one WorkflowCancelledEvent"

        # Verify database state
        workflow_session = workflow.get_session(session_id=session_id)
        assert workflow_session is not None
        assert workflow_session.runs is not None and len(workflow_session.runs) > 0

        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled

        # The key assertion: partial content must be saved
        assert last_run.step_results is not None
        assert len(last_run.step_results) >= 1, "Should have at least one step result with partial content"

        # Find the step result with actual partial content (not just the error message)
        partial_results = [
            sr for sr in last_run.step_results if sr.content and "cancelled" not in (sr.content or "").lower()
        ]
        assert len(partial_results) >= 1, (
            f"Should have partial content saved, got step_results: {last_run.step_results}"
        )

    @pytest.mark.asyncio
    async def test_async_single_step_cancel_preserves_partial_content(self, shared_db):
        """Cancelling a single-step async streaming workflow should save partial content."""
        workflow = Workflow(
            name="Async Single Step Cancel Test",
            db=shared_db,
            steps=[Step(name="streaming_step", executor=async_streaming_executor)],
            telemetry=False,
        )

        session_id = "async_single_step_cancel"
        events_collected = []
        run_id = None

        event_stream = workflow.arun(
            input="test",
            session_id=session_id,
            stream=True,
            stream_events=True,
        )

        async for event in event_stream:
            events_collected.append(event)

            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            # Cancel after receiving content "3"
            if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
                await workflow.acancel_run(run_id)
                async for remaining in event_stream:
                    events_collected.append(remaining)
                break

        # Should have a WorkflowCancelledEvent
        cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
        assert len(cancelled_events) == 1, "Should emit exactly one WorkflowCancelledEvent"

        # Verify database state
        workflow_session = workflow.get_session(session_id=session_id)
        assert workflow_session is not None
        assert workflow_session.runs is not None and len(workflow_session.runs) > 0

        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled

        # The key assertion: partial content must be saved
        assert last_run.step_results is not None
        assert len(last_run.step_results) >= 1, "Should have at least one step result with partial content"

        partial_results = [
            sr for sr in last_run.step_results if sr.content and "cancelled" not in (sr.content or "").lower()
        ]
        assert len(partial_results) >= 1, (
            f"Should have partial content saved, got step_results: {last_run.step_results}"
        )


class TestMultiStepFunctionCancellationStreaming:
    """Multi-step streaming workflow cancellation with function executors (no LLM)."""

    def test_sync_multi_step_cancel_preserves_partial_content(self, shared_db):
        """Cancelling a multi-step workflow at the first step should save partial content."""
        workflow = Workflow(
            name="Multi Step Cancel Test",
            db=shared_db,
            steps=[
                Step(name="streaming_step", executor=sync_streaming_executor),
                Step(name="passthrough_step", executor=sync_passthrough_executor),
            ],
            telemetry=False,
        )

        session_id = "sync_multi_step_cancel"
        events_collected = []
        run_id = None

        event_stream = workflow.run(
            input="test",
            session_id=session_id,
            stream=True,
            stream_events=True,
        )

        for event in event_stream:
            events_collected.append(event)

            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
                workflow.cancel_run(run_id)
                for remaining in event_stream:
                    events_collected.append(remaining)
                break

        cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
        assert len(cancelled_events) == 1

        workflow_session = workflow.get_session(session_id=session_id)
        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled

        assert last_run.step_results is not None
        assert len(last_run.step_results) >= 1

        partial_results = [
            sr for sr in last_run.step_results if sr.content and "cancelled" not in (sr.content or "").lower()
        ]
        assert len(partial_results) >= 1, (
            f"Should have partial content saved, got step_results: {last_run.step_results}"
        )

    @pytest.mark.asyncio
    async def test_async_multi_step_cancel_preserves_partial_content(self, shared_db):
        """Cancelling a multi-step async workflow at the first step should save partial content."""
        workflow = Workflow(
            name="Async Multi Step Cancel Test",
            db=shared_db,
            steps=[
                Step(name="streaming_step", executor=async_streaming_executor),
                Step(name="passthrough_step", executor=async_passthrough_executor),
            ],
            telemetry=False,
        )

        session_id = "async_multi_step_cancel"
        events_collected = []
        run_id = None

        event_stream = workflow.arun(
            input="test",
            session_id=session_id,
            stream=True,
            stream_events=True,
        )

        async for event in event_stream:
            events_collected.append(event)

            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id

            if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
                await workflow.acancel_run(run_id)
                async for remaining in event_stream:
                    events_collected.append(remaining)
                break

        cancelled_events = [e for e in events_collected if isinstance(e, WorkflowCancelledEvent)]
        assert len(cancelled_events) == 1

        workflow_session = workflow.get_session(session_id=session_id)
        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled

        assert last_run.step_results is not None
        assert len(last_run.step_results) >= 1

        partial_results = [
            sr for sr in last_run.step_results if sr.content and "cancelled" not in (sr.content or "").lower()
        ]
        assert len(partial_results) >= 1, (
            f"Should have partial content saved, got step_results: {last_run.step_results}"
        )


# ============================================================================
# NON-STREAMING CANCELLATION TESTS
# ============================================================================


class TestSingleStepCancellationNonStreaming:
    """Single-step non-streaming workflow cancellation."""

    def test_sync_single_step_non_streaming_cancel_sets_cancelled_status(self, shared_db):
        """Cancelling a single-step non-streaming workflow should set CANCELLED status."""
        cancel_event = threading.Event()

        def slow_executor(step_input: StepInput) -> StepOutput:
            # Signal that we've started, then wait
            cancel_event.set()
            for _ in range(50):
                time.sleep(0.05)
            return StepOutput(content="done")

        run_id = "sync_non_stream_cancel_run"
        workflow = Workflow(
            name="Non-Stream Single Step Cancel",
            db=shared_db,
            steps=[Step(name="slow_step", executor=slow_executor)],
            telemetry=False,
        )

        session_id = "sync_non_stream_single_cancel"
        result_holder = {}

        def run_workflow():
            result = workflow.run(
                input="test",
                session_id=session_id,
                run_id=run_id,
                stream=False,
            )
            result_holder["result"] = result

        t = threading.Thread(target=run_workflow)
        t.start()

        # Wait for the executor to actually start
        cancel_event.wait(timeout=5)
        time.sleep(0.1)

        workflow.cancel_run(run_id)
        t.join(timeout=10)

        assert "result" in result_holder, "Workflow should have returned a result"
        result = result_holder["result"]
        assert result.status == RunStatus.cancelled

        workflow_session = workflow.get_session(session_id=session_id)
        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled

    @pytest.mark.asyncio
    async def test_async_single_step_non_streaming_cancel_sets_cancelled_status(self, shared_db):
        """Cancelling a single-step async non-streaming workflow should set CANCELLED status."""
        started = asyncio.Event()

        async def slow_async_executor(step_input: StepInput) -> StepOutput:
            started.set()
            for _ in range(50):
                await asyncio.sleep(0.05)
            return StepOutput(content="done")

        run_id = "async_non_stream_cancel_run"
        workflow = Workflow(
            name="Async Non-Stream Single Step Cancel",
            db=shared_db,
            steps=[Step(name="slow_step", executor=slow_async_executor)],
            telemetry=False,
        )

        session_id = "async_non_stream_single_cancel"

        async def run_workflow():
            return await workflow.arun(
                input="test",
                session_id=session_id,
                run_id=run_id,
                stream=False,
            )

        task = asyncio.create_task(run_workflow())

        # Wait for the executor to actually start
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.sleep(0.1)

        await workflow.acancel_run(run_id)

        result = await asyncio.wait_for(task, timeout=10)

        assert result.status == RunStatus.cancelled

        workflow_session = workflow.get_session(session_id=session_id)
        last_run = workflow_session.runs[-1]
        assert last_run.status == RunStatus.cancelled


# ============================================================================
# ON_ERROR REGRESSION TESTS
# ============================================================================


class TestCancellationDoesNotAffectOnErrorSkip:
    """Verify that on_error='skip' still works for real errors (not cancellation)."""

    def test_on_error_skip_still_works_for_real_errors(self, shared_db):
        """A step that raises a real exception with on_error='skip' should be skipped normally."""

        def failing_executor(step_input: StepInput) -> StepOutput:
            raise ValueError("Intentional test error")

        def success_executor(step_input: StepInput) -> StepOutput:
            return StepOutput(content="success")

        workflow = Workflow(
            name="On Error Skip Test",
            db=shared_db,
            steps=[
                Step(name="failing_step", executor=failing_executor, on_error="skip"),
                Step(name="success_step", executor=success_executor),
            ],
            telemetry=False,
        )

        session_id = "on_error_skip_test"
        result = workflow.run(input="test", session_id=session_id, stream=False)

        # Workflow should complete (not cancel) since the error is a real error, not cancellation
        assert result.status == RunStatus.completed

        # Should have step results for both steps
        assert result.step_results is not None
        assert len(result.step_results) == 2

        # First step should be skipped
        assert result.step_results[0].step_name == "failing_step"
        assert result.step_results[0].success is False
        assert "Intentional test error" in (result.step_results[0].error or "")

        # Second step should succeed
        assert result.step_results[1].step_name == "success_step"
        assert result.step_results[1].content == "success"

    @pytest.mark.asyncio
    async def test_async_on_error_skip_still_works_for_real_errors(self, shared_db):
        """Async: a step that raises a real exception with on_error='skip' should be skipped normally."""

        async def failing_executor(step_input: StepInput) -> StepOutput:
            raise ValueError("Intentional test error")

        async def success_executor(step_input: StepInput) -> StepOutput:
            return StepOutput(content="success")

        workflow = Workflow(
            name="Async On Error Skip Test",
            db=shared_db,
            steps=[
                Step(name="failing_step", executor=failing_executor, on_error="skip"),
                Step(name="success_step", executor=success_executor),
            ],
            telemetry=False,
        )

        session_id = "async_on_error_skip_test"
        result = await workflow.arun(input="test", session_id=session_id, stream=False)

        assert result.status == RunStatus.completed

        assert result.step_results is not None
        assert len(result.step_results) == 2

        assert result.step_results[0].step_name == "failing_step"
        assert result.step_results[0].success is False
        assert "Intentional test error" in (result.step_results[0].error or "")

        assert result.step_results[1].step_name == "success_step"
        assert result.step_results[1].content == "success"


# ============================================================================
# NESTED PRIMITIVE CANCELLATION TESTS (Loop / Parallel / Condition / Router / Steps)
# ============================================================================


def _cancel_after_third_content(workflow, session_id):
    """Stream a workflow, cancel after content '3', drain, and return collected events."""
    events = []
    run_id = None
    stream = workflow.run(input="test", session_id=session_id, stream=True, stream_events=True)
    for event in stream:
        events.append(event)
        if run_id is None and hasattr(event, "run_id"):
            run_id = event.run_id
        if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
            workflow.cancel_run(run_id)
            for remaining in stream:
                events.append(remaining)
            break
    return events


class TestNestedPrimitiveCancellation:
    """Cancellation must propagate + persist through Loop/Parallel/Condition/Router/Steps."""

    def test_loop_streaming_cancel_persists(self, shared_db):
        """Cancelling a streaming Loop propagates the cancel and persists status=cancelled."""
        workflow = Workflow(
            name="Loop Cancel",
            db=shared_db,
            telemetry=False,
            steps=[
                Loop(
                    name="loop",
                    max_iterations=5,
                    steps=[Step(name="ls", executor=sync_streaming_executor)],
                    end_condition=lambda outputs: False,
                )
            ],
        )
        events = _cancel_after_third_content(workflow, "wf_loop_cancel")
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id="wf_loop_cancel").runs[-1]
        assert last_run.status == RunStatus.cancelled

    def test_parallel_streaming_cancel_persists(self, shared_db):
        """Cancelling a streaming Parallel propagates the cancel and persists status=cancelled."""
        workflow = Workflow(
            name="Parallel Cancel",
            db=shared_db,
            telemetry=False,
            steps=[
                Parallel(
                    Step(name="p1", executor=sync_streaming_executor),
                    Step(name="p2", executor=sync_streaming_executor),
                    name="par",
                )
            ],
        )
        events = _cancel_after_third_content(workflow, "wf_parallel_cancel")
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id="wf_parallel_cancel").runs[-1]
        assert last_run.status == RunStatus.cancelled

    def test_condition_streaming_cancel_persists(self, shared_db):
        """Cancelling a streaming Condition propagates the cancel and persists status=cancelled."""
        workflow = Workflow(
            name="Condition Cancel",
            db=shared_db,
            telemetry=False,
            steps=[
                Condition(
                    name="cond",
                    evaluator=lambda step_input: True,
                    steps=[Step(name="cs", executor=sync_streaming_executor)],
                )
            ],
        )
        events = _cancel_after_third_content(workflow, "wf_condition_cancel")
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id="wf_condition_cancel").runs[-1]
        assert last_run.status == RunStatus.cancelled

    def test_router_streaming_cancel_persists(self, shared_db):
        """Cancelling a streaming Router propagates the cancel and persists status=cancelled."""
        routed = Step(name="rs", executor=sync_streaming_executor)
        workflow = Workflow(
            name="Router Cancel",
            db=shared_db,
            telemetry=False,
            steps=[Router(name="router", choices=[routed], selector=lambda step_input: routed)],
        )
        events = _cancel_after_third_content(workflow, "wf_router_cancel")
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id="wf_router_cancel").runs[-1]
        assert last_run.status == RunStatus.cancelled

    def test_nested_steps_streaming_cancel_persists(self, shared_db):
        """Cancelling a streaming nested Steps propagates the cancel and persists status=cancelled."""
        inner = Steps(name="inner", steps=[Step(name="ns", executor=sync_streaming_executor)])
        workflow = Workflow(name="Nested Cancel", db=shared_db, telemetry=False, steps=[inner])
        events = _cancel_after_third_content(workflow, "wf_nested_cancel")
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id="wf_nested_cancel").runs[-1]
        assert last_run.status == RunStatus.cancelled

    @pytest.mark.asyncio
    async def test_async_loop_streaming_cancel_persists(self, shared_db):
        """Cancelling an async streaming Loop propagates the cancel and persists status=cancelled."""
        workflow = Workflow(
            name="Async Loop Cancel",
            db=shared_db,
            telemetry=False,
            steps=[
                Loop(
                    name="loop",
                    max_iterations=5,
                    steps=[Step(name="ls", executor=async_streaming_executor)],
                    end_condition=lambda outputs: False,
                )
            ],
        )
        session_id = "wf_async_loop_cancel"
        events = []
        run_id = None
        stream = workflow.arun(input="test", session_id=session_id, stream=True, stream_events=True)
        async for event in stream:
            events.append(event)
            if run_id is None and hasattr(event, "run_id"):
                run_id = event.run_id
            if isinstance(event, RunContentEvent) and event.content == "3" and run_id:
                await workflow.acancel_run(run_id)
                async for remaining in stream:
                    events.append(remaining)
                break
        assert len([e for e in events if isinstance(e, WorkflowCancelledEvent)]) == 1
        last_run = workflow.get_session(session_id=session_id).runs[-1]
        assert last_run.status == RunStatus.cancelled

    def test_loop_non_streaming_cancels_between_iterations(self, shared_db):
        """Regression: non-streaming Loop must check cancellation between iterations.

        The step executor does NOT check cancellation itself, so the only checkpoint is
        the loop's per-iteration check. A background thread cancels mid-run; the loop must
        stop with status=cancelled rather than running all iterations to completion.
        """

        def sleepy_step(step_input: StepInput) -> StepOutput:
            time.sleep(0.25)  # no cancellation check inside the step
            return StepOutput(content="iteration done")

        workflow = Workflow(
            name="NonStream Loop Cancel",
            db=shared_db,
            telemetry=False,
            steps=[
                Loop(
                    name="loop",
                    max_iterations=10,
                    steps=[Step(name="ls", executor=sleepy_step)],
                    end_condition=lambda outputs: False,
                )
            ],
        )

        session_id = "wf_nonstream_loop_cancel"
        run_id = "nonstream-loop-run"

        def cancel_soon():
            time.sleep(0.4)  # let the loop start, then cancel mid-run
            cancel_run(run_id)

        canceller = threading.Thread(target=cancel_soon)
        canceller.start()
        result = workflow.run(input="test", session_id=session_id, run_id=run_id, stream=False)
        canceller.join()

        assert result.status == RunStatus.cancelled, f"expected cancelled, got {result.status}"
        last_run = workflow.get_session(session_id=session_id).runs[-1]
        assert last_run.status == RunStatus.cancelled

"""Integration tests for Parallel steps functionality."""

import pytest

from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.workflow.v2 import Workflow
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput


# Simple step functions for testing
def step_a(step_input: StepInput) -> StepOutput:
    """Test step A."""
    return StepOutput(content="Output A")


def step_b(step_input: StepInput) -> StepOutput:
    """Test step B."""
    return StepOutput(content="Output B")


def final_step(step_input: StepInput) -> StepOutput:
    """Combine previous outputs."""
    return StepOutput(content=f"Final: {step_input.get_all_previous_content()}")


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_parallel_direct_execute():
    """Test Parallel.execute() directly without workflow."""
    parallel = Parallel(step_a, step_b, name="Direct Parallel")
    step_input = StepInput(message="direct test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Parallel"
    assert "Output A" in result.content
    assert "Output B" in result.content
    assert "SUCCESS: step_a" in result.content
    assert "SUCCESS: step_b" in result.content


@pytest.mark.asyncio
async def test_parallel_direct_aexecute():
    """Test Parallel.aexecute() directly without workflow."""
    parallel = Parallel(step_a, step_b, name="Direct Async Parallel")
    step_input = StepInput(message="direct async test")

    result = await parallel.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Async Parallel"
    assert "Output A" in result.content
    assert "Output B" in result.content


def test_parallel_direct_execute_stream():
    """Test Parallel.execute_stream() directly without workflow."""
    from agno.run.v2.workflow import ParallelExecutionCompletedEvent, ParallelExecutionStartedEvent, WorkflowRunResponse

    parallel = Parallel(step_a, step_b, name="Direct Stream Parallel")
    step_input = StepInput(message="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunResponse(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(
        parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_intermediate_steps=True)
    )

    # Should have started, completed events and final result
    started_events = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 1
    assert started_events[0].parallel_step_count == 2
    assert "Output A" in step_outputs[0].content


def test_parallel_direct_single_step():
    """Test Parallel with single step."""
    parallel = Parallel(step_a, name="Single Step Parallel")
    step_input = StepInput(message="single test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Single Step Parallel"
    assert result.content == "Output A"  # Single step, no aggregation


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_parallel(workflow_storage):
    """Test basic parallel execution."""
    workflow = Workflow(
        name="Basic Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2

    # Check parallel output
    parallel_output = response.step_responses[0]
    assert isinstance(parallel_output, StepOutput)
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content


def test_parallel_streaming(workflow_storage):
    """Test parallel execution with streaming."""
    workflow = Workflow(
        name="Streaming Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = list(workflow.run(message="test", stream=True, stream_intermediate_steps=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None


def test_parallel_with_agent(workflow_storage, test_agent):
    """Test parallel execution with agent step."""
    agent_step = Step(name="agent_step", agent=test_agent)

    workflow = Workflow(
        name="Agent Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, agent_step, name="Mixed Parallel"), final_step],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    parallel_output = response.step_responses[0]
    assert isinstance(parallel_output, StepOutput)
    assert "Output A" in parallel_output.content


@pytest.mark.asyncio
async def test_async_parallel(workflow_storage):
    """Test async parallel execution."""
    workflow = Workflow(
        name="Async Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = await workflow.arun(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2


@pytest.mark.asyncio
async def test_async_parallel_streaming(workflow_storage):
    """Test async parallel execution with streaming."""
    workflow = Workflow(
        name="Async Streaming Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True, stream_intermediate_steps=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

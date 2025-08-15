"""Integration tests for Parallel steps functionality."""

import pytest

from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.workflow import Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


def find_content_in_steps(step_output, search_text):
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


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
    step_input = StepInput(input="direct test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Parallel"
    assert result.step_type == "Parallel"
    assert "Parallel Direct Parallel completed with 2 results" in result.content

    # The actual step outputs should be in the steps field
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


@pytest.mark.asyncio
async def test_parallel_direct_aexecute():
    """Test Parallel.aexecute() directly without workflow."""
    parallel = Parallel(step_a, step_b, name="Direct Async Parallel")
    step_input = StepInput(input="direct async test")

    result = await parallel.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Async Parallel"
    assert result.step_type == "Parallel"
    assert "Parallel Direct Async Parallel completed with 2 results" in result.content

    # The actual step outputs should be in the steps field
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


def test_parallel_direct_execute_stream():
    """Test Parallel.execute_stream() directly without workflow."""
    from agno.run.workflow import ParallelExecutionCompletedEvent, ParallelExecutionStartedEvent, WorkflowRunOutput

    parallel = Parallel(step_a, step_b, name="Direct Stream Parallel")
    step_input = StepInput(input="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunOutput(
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

    # Check the parallel container output
    parallel_output = step_outputs[0]
    assert "Parallel Direct Stream Parallel completed with 2 results" in parallel_output.content
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    assert find_content_in_steps(parallel_output, "Output B")


def test_parallel_direct_single_step():
    """Test Parallel with single step."""
    parallel = Parallel(step_a, name="Single Step Parallel")
    step_input = StepInput(input="single test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Single Step Parallel"
    assert result.step_type == "Parallel"
    assert "Parallel Single Step Parallel completed with 1 result" in result.content

    # Single step should still be in the steps field
    assert len(result.steps) == 1
    assert result.steps[0].content == "Output A"


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_parallel(shared_db):
    """Test basic parallel execution."""
    workflow = Workflow(
        name="Basic Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Check parallel output
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"
    assert "Parallel Parallel Phase completed with 2 results" in parallel_output.content

    # The actual step outputs should be in the nested steps
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    assert find_content_in_steps(parallel_output, "Output B")


def test_parallel_streaming(shared_db):
    """Test parallel execution with streaming."""
    workflow = Workflow(
        name="Streaming Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = list(workflow.run(input="test", stream=True, stream_intermediate_steps=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

    # Check that the parallel output has nested steps
    final_response = completed_events[0]
    parallel_output = final_response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2


def test_parallel_with_agent(shared_db, test_agent):
    """Test parallel execution with agent step."""
    agent_step = Step(name="agent_step", agent=test_agent)

    workflow = Workflow(
        name="Agent Parallel",
        db=shared_db,
        steps=[Parallel(step_a, agent_step, name="Mixed Parallel"), final_step],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"
    assert "Parallel Mixed Parallel completed with 2 results" in parallel_output.content

    # Check nested steps contain both function and agent outputs
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    # Agent output will vary, but should be present in nested steps


@pytest.mark.asyncio
async def test_async_parallel(shared_db):
    """Test async parallel execution."""
    workflow = Workflow(
        name="Async Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = await workflow.arun(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Check parallel output structure
    parallel_output = response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2


@pytest.mark.asyncio
async def test_async_parallel_streaming(shared_db):
    """Test async parallel execution with streaming."""
    workflow = Workflow(
        name="Async Streaming Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = []
    async for event in await workflow.arun(input="test", stream=True, stream_intermediate_steps=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

    # Check parallel structure in final result
    final_response = completed_events[0]
    parallel_output = final_response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2

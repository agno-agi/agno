"""Integration tests for Parallel steps functionality."""

from contextvars import ContextVar
from secrets import token_hex

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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content
    assert "Output B" in result.content

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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content
    assert "Output B" in result.content

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

    events = list(parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))

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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content
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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content

    # Single step should still be in the steps field
    assert len(result.steps) == 1
    assert result.steps[0].content == "Output A"


# ============================================================================
# CONTEXT PROPAGATION TESTS
# ============================================================================

# ContextVar for testing context propagation to child threads
_test_context_var: ContextVar[str] = ContextVar("test_context_var", default="not_set")


def _step_read_context(step_input: StepInput) -> StepOutput:
    """Step that reads a context variable to verify propagation."""
    value = _test_context_var.get()
    return StepOutput(content=f"context_value={value}")


def test_parallel_context_propagation():
    """Test that context variables are propagated to parallel step threads.

    This verifies that copy_context().run() is used when submitting tasks
    to the ThreadPoolExecutor, ensuring contextvars are available in child threads.
    """
    # Set context variable in main thread
    value = token_hex(16)
    token = _test_context_var.set(value)

    try:
        parallel = Parallel(
            _step_read_context,
            _step_read_context,
            name="Context Propagation Test",
        )
        step_input = StepInput(input="context test")

        result = parallel.execute(step_input)

        # Both parallel steps should have received the context variable
        assert len(result.steps) == 2
        for step_result in result.steps:
            assert f"context_value={value}" in step_result.content, (
                f"Context variable was not propagated to child thread. Got: {step_result.content}"
            )
    finally:
        _test_context_var.reset(token)


def test_parallel_context_propagation_streaming():
    """Test context propagation in streaming parallel execution."""
    from agno.run.workflow import WorkflowRunOutput

    value = token_hex(16)
    token = _test_context_var.set(value)

    try:
        parallel = Parallel(
            _step_read_context,
            _step_read_context,
            name="Context Stream Test",
        )
        step_input = StepInput(input="context stream test")

        mock_response = WorkflowRunOutput(
            run_id="test-run",
            workflow_name="test-workflow",
            workflow_id="test-id",
            session_id="test-session",
            content="",
        )

        events = list(parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))
        step_outputs = [e for e in events if isinstance(e, StepOutput)]

        assert len(step_outputs) == 1
        parallel_output = step_outputs[0]
        assert len(parallel_output.steps) == 2

        for step_result in parallel_output.steps:
            assert f"context_value={value}" in step_result.content, (
                f"Context variable was not propagated in streaming mode. Got: {step_result.content}"
            )
    finally:
        _test_context_var.reset(token)


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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content

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

    events = list(workflow.run(input="test", stream=True, stream_events=True))
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
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content

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
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

    # Check parallel structure in final result
    final_response = completed_events[0]
    parallel_output = final_response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2

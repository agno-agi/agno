"""Integration tests for Loop functionality in workflows."""

import pytest

from agno.run.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Loop, Parallel, Workflow
from agno.workflow.types import StepInput, StepOutput


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step that generates content."""
    return StepOutput(step_name="research", content="Found research data about AI trends", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(step_name="analysis", content="Analyzed AI trends data", success=True)


def summary_step(step_input: StepInput) -> StepOutput:
    """Summary step."""
    return StepOutput(step_name="summary", content="Summary of findings", success=True)


# Helper function to recursively search for content in nested steps
def find_content_in_steps(step_output: StepOutput, search_text: str) -> bool:
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_loop_direct_execute():
    """Test Loop.execute() directly without workflow."""

    def simple_end_condition(outputs):
        return len(outputs) >= 2

    loop = Loop(name="Direct Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=3)
    step_input = StepInput(input="direct test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) >= 2  # Should stop when condition is met
    assert all("AI trends" in output.content for output in result.steps)


@pytest.mark.asyncio
async def test_loop_direct_aexecute():
    """Test Loop.aexecute() directly without workflow."""

    def simple_end_condition(outputs):
        return len(outputs) >= 2

    loop = Loop(name="Direct Async Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=3)
    step_input = StepInput(input="direct async test")

    result = await loop.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) >= 2
    assert all("AI trends" in output.content for output in result.steps)


def test_loop_direct_execute_stream():
    """Test Loop.execute_stream() directly without workflow."""
    from agno.run.workflow import LoopIterationCompletedEvent, LoopIterationStartedEvent, WorkflowRunOutput

    def simple_end_condition(outputs):
        return len(outputs) >= 1

    loop = Loop(name="Direct Stream Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=2)
    step_input = StepInput(input="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(loop.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))

    # Should have started, completed, iteration events and step outputs
    started_events = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    iteration_started = [e for e in events if isinstance(e, LoopIterationStartedEvent)]
    iteration_completed = [e for e in events if isinstance(e, LoopIterationCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(iteration_started) >= 1
    assert len(iteration_completed) >= 1
    assert len(step_outputs) >= 1
    assert started_events[0].max_iterations == 2


def test_loop_direct_max_iterations():
    """Test Loop respects max_iterations."""

    def never_end_condition(outputs):
        return False  # Never end

    loop = Loop(name="Max Iterations Loop", steps=[research_step], end_condition=never_end_condition, max_iterations=2)
    step_input = StepInput(input="max iterations test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2  # Should stop at max_iterations


def test_loop_direct_no_end_condition():
    """Test Loop without end condition (uses max_iterations only)."""
    loop = Loop(name="No End Condition Loop", steps=[research_step], max_iterations=3)
    step_input = StepInput(input="no condition test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 3  # Should run all iterations


def test_loop_direct_multiple_steps():
    """Test Loop with multiple steps per iteration."""

    def simple_end_condition(outputs):
        return len(outputs) >= 2  # 2 outputs = 1 iteration (2 steps)

    loop = Loop(
        name="Multi Step Loop",
        steps=[research_step, analysis_step],
        end_condition=simple_end_condition,
        max_iterations=3,
    )
    step_input = StepInput(input="multi step test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) >= 2
    # Should have both research and analysis outputs
    research_outputs = [r for r in result.steps if "research data" in r.content]
    analysis_outputs = [r for r in result.steps if "Analyzed" in r.content]
    assert len(research_outputs) >= 1
    assert len(analysis_outputs) >= 1


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_loop(shared_db):
    """Test basic loop with multiple steps."""

    def check_content(outputs):
        """Stop when we have enough content."""
        return any("AI trends" in o.content for o in outputs)

    workflow = Workflow(
        name="Basic Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[research_step, analysis_step],
                end_condition=check_content,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    assert find_content_in_steps(response.step_results[0], "AI trends")


def test_loop_with_parallel(shared_db):
    """Test loop with parallel steps."""

    def check_content(outputs):
        """Stop when both research and analysis are done."""
        has_research = any("research data" in o.content for o in outputs)
        has_analysis = any("Analyzed" in o.content for o in outputs)
        return has_research and has_analysis

    workflow = Workflow(
        name="Parallel Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(research_step, analysis_step, name="Parallel Research & Analysis"), summary_step],
                end_condition=check_content,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)

    # Check the loop step output in step_results
    loop_step_output = response.step_results[0]  # First step (Loop)
    assert isinstance(loop_step_output, StepOutput)
    assert loop_step_output.step_type == "Loop"

    # Check nested parallel and summary step outputs
    parallel_output = loop_step_output.steps[0] if loop_step_output.steps else None
    assert parallel_output is not None
    assert parallel_output.step_type == "Parallel"


def test_loop_streaming(shared_db):
    """Test loop with streaming events."""
    workflow = Workflow(
        name="Streaming Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[research_step],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1
    assert len(workflow_completed) == 1


def test_parallel_loop_streaming(shared_db):
    """Test parallel steps in loop with streaming."""
    workflow = Workflow(
        name="Parallel Streaming Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(research_step, analysis_step, name="Parallel Steps")],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


@pytest.mark.asyncio
async def test_async_loop(shared_db):
    """Test async loop execution."""

    async def async_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_step", content="Async research: AI trends", success=True)

    workflow = Workflow(
        name="Async Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[async_step],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    response = await workflow.arun(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert find_content_in_steps(response.step_results[0], "AI trends")


@pytest.mark.asyncio
async def test_async_parallel_loop(shared_db):
    """Test async loop with parallel steps."""

    async def async_research(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_research", content="Async research: AI trends", success=True)

    async def async_analysis(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_analysis", content="Async analysis complete", success=True)

    workflow = Workflow(
        name="Async Parallel Loop",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(async_research, async_analysis, name="Async Parallel Steps")],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    response = await workflow.arun(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert find_content_in_steps(response.step_results[0], "AI trends")

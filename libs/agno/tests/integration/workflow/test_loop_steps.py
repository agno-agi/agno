"""Integration tests for Loop functionality in workflows."""

import pytest

from agno.run.v2.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.workflow.v2 import Loop, Parallel, Workflow
from agno.workflow.v2.types import StepInput, StepOutput


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


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_loop_direct_execute():
    """Test Loop.execute() directly without workflow."""

    def simple_end_condition(outputs):
        return len(outputs) >= 2

    loop = Loop(name="Direct Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=3)
    step_input = StepInput(message="direct test")

    result = loop.execute(step_input)

    assert isinstance(result, list)
    assert len(result) >= 2  # Should stop when condition is met
    assert all("AI trends" in output.content for output in result)


@pytest.mark.asyncio
async def test_loop_direct_aexecute():
    """Test Loop.aexecute() directly without workflow."""

    def simple_end_condition(outputs):
        return len(outputs) >= 2

    loop = Loop(name="Direct Async Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=3)
    step_input = StepInput(message="direct async test")

    result = await loop.aexecute(step_input)

    assert isinstance(result, list)
    assert len(result) >= 2
    assert all("AI trends" in output.content for output in result)


def test_loop_direct_execute_stream():
    """Test Loop.execute_stream() directly without workflow."""
    from agno.run.v2.workflow import LoopIterationCompletedEvent, LoopIterationStartedEvent, WorkflowRunResponse

    def simple_end_condition(outputs):
        return len(outputs) >= 1

    loop = Loop(name="Direct Stream Loop", steps=[research_step], end_condition=simple_end_condition, max_iterations=2)
    step_input = StepInput(message="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunResponse(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(loop.execute_stream(step_input, workflow_run_response=mock_response, stream_intermediate_steps=True))

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
    step_input = StepInput(message="max iterations test")

    result = loop.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 2  # Should stop at max_iterations


def test_loop_direct_no_end_condition():
    """Test Loop without end condition (uses max_iterations only)."""
    loop = Loop(name="No End Condition Loop", steps=[research_step], max_iterations=3)
    step_input = StepInput(message="no condition test")

    result = loop.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 3  # Should run all iterations


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
    step_input = StepInput(message="multi step test")

    result = loop.execute(step_input)

    assert isinstance(result, list)
    assert len(result) >= 2
    # Should have both research and analysis outputs
    research_outputs = [r for r in result if "research data" in r.content]
    analysis_outputs = [r for r in result if "Analyzed" in r.content]
    assert len(research_outputs) >= 1
    assert len(analysis_outputs) >= 1


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_loop(workflow_storage):
    """Test basic loop with multiple steps."""

    def check_content(outputs):
        """Stop when we have enough content."""
        return any("AI trends" in o.content for o in outputs)

    workflow = Workflow(
        name="Basic Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[research_step, analysis_step],
                end_condition=check_content,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    assert "AI trends" in response.content


def test_loop_with_parallel(workflow_storage):
    """Test loop with parallel steps."""

    def check_content(outputs):
        """Stop when both research and analysis are done."""
        has_research = any("research data" in o.content for o in outputs)
        has_analysis = any("Analyzed" in o.content for o in outputs)
        return has_research and has_analysis

    workflow = Workflow(
        name="Parallel Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(research_step, analysis_step, name="Parallel Research & Analysis"), summary_step],
                end_condition=check_content,
                max_iterations=3,
            )
        ],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)

    # Check the parallel step output in step_responses
    parallel_step_output = response.step_responses[0][0]  # First step's first output
    assert "research data" in parallel_step_output.content
    assert "Analyzed" in parallel_step_output.content

    # Check summary step output
    summary_step_output = response.step_responses[0][1]  # First step's second output
    assert "Summary of findings" in summary_step_output.content


def test_loop_streaming(workflow_storage):
    """Test loop with streaming events."""
    workflow = Workflow(
        name="Streaming Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[research_step],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True, stream_intermediate_steps=True))

    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1
    assert len(workflow_completed) == 1


def test_parallel_loop_streaming(workflow_storage):
    """Test parallel steps in loop with streaming."""
    workflow = Workflow(
        name="Parallel Streaming Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(research_step, analysis_step, name="Parallel Steps")],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True, stream_intermediate_steps=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


@pytest.mark.asyncio
async def test_async_loop(workflow_storage):
    """Test async loop execution."""

    async def async_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_step", content="Async research: AI trends", success=True)

    workflow = Workflow(
        name="Async Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[async_step],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    response = await workflow.arun(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert "AI trends" in response.content


@pytest.mark.asyncio
async def test_async_parallel_loop(workflow_storage):
    """Test async loop with parallel steps."""

    async def async_research(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_research", content="Async research: AI trends", success=True)

    async def async_analysis(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="async_analysis", content="Async analysis complete", success=True)

    workflow = Workflow(
        name="Async Parallel Loop",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[Parallel(async_research, async_analysis, name="Async Parallel Steps")],
                end_condition=lambda outputs: "AI trends" in outputs[-1].content,
                max_iterations=3,
            )
        ],
    )

    response = await workflow.arun(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert "AI trends" in response.content

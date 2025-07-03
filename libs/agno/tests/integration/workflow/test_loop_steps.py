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

    events = list(workflow.run(message="test", stream=True))

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

    events = list(workflow.run(message="test", stream=True))
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

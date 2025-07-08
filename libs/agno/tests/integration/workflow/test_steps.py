"""Integration tests for Steps functionality in workflows."""

import asyncio
from typing import AsyncIterator

import pytest

from agno.run.v2.workflow import (
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    WorkflowCompletedEvent,
)
from agno.workflow.v2 import Step, StepInput, StepOutput, Steps, Workflow


# Simple helper functions
def step1_function(step_input: StepInput) -> StepOutput:
    """First step function."""
    return StepOutput(content=f"Step1: {step_input.message}")


def step2_function(step_input: StepInput) -> StepOutput:
    """Second step function that uses previous output."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Step2: {prev}")


def step3_function(step_input: StepInput) -> StepOutput:
    """Third step function."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Step3: {prev}")


async def async_step_function(step_input: StepInput) -> StepOutput:
    """Async step function."""
    await asyncio.sleep(0.001)
    return StepOutput(content=f"AsyncStep: {step_input.message}")


async def async_streaming_function(step_input: StepInput) -> AsyncIterator[str]:
    """Async streaming step function."""
    yield f"Streaming: {step_input.message}"
    await asyncio.sleep(0.001)


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_steps_direct_execute():
    """Test Steps.execute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Steps", steps=[step1, step2])
    step_input = StepInput(message="direct test")

    result = steps.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 2
    assert "Step1: direct test" in result[0].content
    assert "Step2: Step1: direct test" in result[1].content


@pytest.mark.asyncio
async def test_steps_direct_aexecute():
    """Test Steps.aexecute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Async Steps", steps=[step1, step2])
    step_input = StepInput(message="direct async test")

    result = await steps.aexecute(step_input)

    assert isinstance(result, list)
    assert len(result) == 2
    assert "Step1: direct async test" in result[0].content
    assert "Step2: Step1: direct async test" in result[1].content


def test_steps_direct_execute_stream():
    """Test Steps.execute_stream() directly without workflow."""
    from agno.run.v2.workflow import WorkflowRunResponse

    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Stream Steps", steps=[step1, step2])
    step_input = StepInput(message="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunResponse(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(steps.execute_stream(step_input, mock_response, stream_intermediate_steps=True))

    # Should have started, completed events and step outputs
    started_events = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 2
    assert started_events[0].steps_count == 2


def test_steps_direct_empty():
    """Test Steps with no internal steps."""
    steps = Steps(name="Empty Steps", steps=[])
    step_input = StepInput(message="test")

    result = steps.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 1
    assert "No steps to execute" in result[0].content


def test_steps_direct_single_step():
    """Test Steps with single step."""
    step1 = Step(name="step1", executor=step1_function)
    steps = Steps(name="Single Step", steps=[step1])
    step_input = StepInput(message="single test")

    result = steps.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 1
    assert "Step1: single test" in result[0].content


def test_steps_direct_chaining():
    """Test Steps properly chains outputs."""
    step1 = Step(name="first", executor=lambda x: StepOutput(content="first_output"))
    step2 = Step(name="second", executor=lambda x: StepOutput(content=f"second_{x.previous_step_content}"))
    step3 = Step(name="third", executor=lambda x: StepOutput(content=f"third_{x.previous_step_content}"))

    steps = Steps(name="Chaining Steps", steps=[step1, step2, step3])
    step_input = StepInput(message="test")

    result = steps.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0].content == "first_output"
    assert result[1].content == "second_first_output"
    assert result[2].content == "third_second_first_output"


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_steps_execution(workflow_storage):
    """Test basic Steps execution - sync non-streaming."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps_sequence = Steps(name="test_steps", steps=[step1, step2])

    workflow = Workflow(
        name="Basic Steps Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    response = workflow.run(message="test message")

    assert len(response.step_responses) == 1
    assert "Step2: Step1: test message" in response.content


def test_steps_streaming(workflow_storage):
    """Test Steps execution - sync streaming."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps_sequence = Steps(name="streaming_steps", steps=[step1, step2])

    workflow = Workflow(
        name="Streaming Steps Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    events = list(workflow.run(message="stream test", stream=True, stream_intermediate_steps=True))

    # Check for required events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(steps_started) == 1
    assert len(steps_completed) == 1
    assert len(workflow_completed) == 1

    # Check final content
    final_response = workflow_completed[0]
    assert "Step2: Step1: stream test" in final_response.content


@pytest.mark.asyncio
async def test_async_steps_execution(workflow_storage):
    """Test Steps execution - async non-streaming."""
    async_step = Step(name="async_step", executor=async_step_function)
    regular_step = Step(name="regular_step", executor=step2_function)

    steps_sequence = Steps(name="async_steps", steps=[async_step, regular_step])

    workflow = Workflow(
        name="Async Steps Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    response = await workflow.arun(message="async test")

    assert len(response.step_responses) == 1
    assert "Step2: AsyncStep: async test" in response.content


@pytest.mark.asyncio
async def test_async_steps_streaming(workflow_storage):
    """Test Steps execution - async streaming."""
    async_streaming_step = Step(name="async_streaming", executor=async_streaming_function)
    regular_step = Step(name="regular_step", executor=step2_function)

    steps_sequence = Steps(name="async_streaming_steps", steps=[async_streaming_step, regular_step])

    workflow = Workflow(
        name="Async Streaming Steps Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    events = []
    async for event in await workflow.arun(message="async stream test", stream=True, stream_intermediate_steps=True):
        events.append(event)

    # Check that we have events
    assert len(events) > 0

    # Check for workflow completion
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_steps_chaining(workflow_storage):
    """Test that steps properly chain outputs."""
    step1 = Step(name="first", executor=lambda x: StepOutput(content="first_output"))
    step2 = Step(name="second", executor=lambda x: StepOutput(content=f"second_{x.previous_step_content}"))
    step3 = Step(name="third", executor=lambda x: StepOutput(content=f"third_{x.previous_step_content}"))

    steps_sequence = Steps(name="chaining_steps", steps=[step1, step2, step3])

    workflow = Workflow(
        name="Chaining Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    response = workflow.run(message="test")

    # Should chain through all steps
    assert "third_second_first_output" in response.content


def test_empty_steps(workflow_storage):
    """Test Steps with no internal steps."""
    empty_steps = Steps(name="empty_steps", steps=[])

    workflow = Workflow(
        name="Empty Steps Test",
        storage=workflow_storage,
        steps=[empty_steps],
    )

    response = workflow.run(message="test")

    assert response.content == "No steps to execute"


def test_steps_media_aggregation(workflow_storage):
    """Test Steps media aggregation."""
    step1 = Step(name="step1", executor=lambda x: StepOutput(content="content1", images=["image1.jpg"]))
    step2 = Step(name="step2", executor=lambda x: StepOutput(content="content2", videos=["video1.mp4"]))
    step3 = Step(name="step3", executor=lambda x: StepOutput(content="content3", audio=["audio1.mp3"]))

    steps_sequence = Steps(name="media_steps", steps=[step1, step2, step3])

    workflow = Workflow(
        name="Media Test",
        storage=workflow_storage,
        steps=[steps_sequence],
    )

    response = workflow.run(message="test")

    # Should have aggregated media
    assert len(response.images) == 1
    assert len(response.videos) == 1
    assert len(response.audio) == 1
    # Content should be from last step
    assert "content3" in response.content


def test_nested_steps(workflow_storage):
    """Test nested Steps."""
    inner_step1 = Step(name="inner1", executor=lambda x: StepOutput(content="inner1"))
    inner_step2 = Step(name="inner2", executor=lambda x: StepOutput(content=f"inner2_{x.previous_step_content}"))

    inner_steps = Steps(name="inner_steps", steps=[inner_step1, inner_step2])
    outer_step = Step(name="outer", executor=lambda x: StepOutput(content=f"outer_{x.previous_step_content}"))

    outer_steps = Steps(name="outer_steps", steps=[inner_steps, outer_step])

    workflow = Workflow(
        name="Nested Test",
        storage=workflow_storage,
        steps=[outer_steps],
    )

    response = workflow.run(message="test")

    # Should chain through nested structure
    assert "outer_inner2_inner1" in response.content


def test_steps_with_other_workflow_steps(workflow_storage):
    """Test Steps in workflow with other steps."""
    individual_step = Step(name="individual", executor=lambda x: StepOutput(content="individual_output"))

    step1 = Step(name="grouped1", executor=lambda x: StepOutput(content=f"grouped1_{x.previous_step_content}"))
    step2 = Step(name="grouped2", executor=lambda x: StepOutput(content=f"grouped2_{x.previous_step_content}"))
    grouped_steps = Steps(name="grouped_steps", steps=[step1, step2])

    final_step = Step(name="final", executor=lambda x: StepOutput(content=f"final_{x.previous_step_content}"))

    workflow = Workflow(
        name="Mixed Workflow",
        storage=workflow_storage,
        steps=[individual_step, grouped_steps, final_step],
    )

    response = workflow.run(message="test")

    assert len(response.step_responses) == 3
    assert "final_grouped2_grouped1_individual_output" in response.content

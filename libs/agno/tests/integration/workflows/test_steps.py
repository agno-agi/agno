"""Integration tests for Steps functionality in workflows."""

import asyncio
from typing import AsyncIterator

import pytest

from agno.run.workflow import (
    StepCompletedEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Step, StepInput, StepOutput, Steps, Workflow


def find_content_in_steps(step_output, search_text):
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


# Simple helper functions
def step1_function(step_input: StepInput) -> StepOutput:
    """First step function."""
    return StepOutput(content=f"Step1: {step_input.input}")


def step2_function(step_input: StepInput) -> StepOutput:
    """Second step function that uses previous output."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Step2: {prev}")


def step3_function(step_input: StepInput) -> StepOutput:
    """Third step function."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Step3: {prev}")


class StepClassWithCallable:
    def __call__(self, step_input: StepInput) -> StepOutput:
        prev = step_input.previous_step_content or ""
        return StepOutput(content=f"StepClassWithCallable: {prev}")


async def async_step_function(step_input: StepInput) -> StepOutput:
    """Async step function."""
    await asyncio.sleep(0.001)
    return StepOutput(content=f"AsyncStep: {step_input.input}")


class AsyncStepClassWithCallable:
    async def __call__(self, step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content=f"AsyncStepClassWithCallable: {step_input.input}")


async def async_streaming_function(step_input: StepInput) -> AsyncIterator[str]:
    """Async streaming step function."""
    yield f"Streaming: {step_input.input}"
    await asyncio.sleep(0.001)


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_steps_direct_execute():
    """Test Steps.execute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Steps", steps=[step1, step2])
    step_input = StepInput(input="direct test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Step1: direct test")
    assert find_content_in_steps(result, "Step2: Step1: direct test")


def test_steps_direct_execute_with_callable_class():
    """Test Steps.execute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=StepClassWithCallable())

    steps = Steps(name="Direct Steps", steps=[step1, step2])
    step_input = StepInput(input="direct test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Step1: direct test")
    assert find_content_in_steps(result, "StepClassWithCallable: Step1: direct test")


@pytest.mark.asyncio
async def test_steps_direct_aexecute():
    """Test Steps.aexecute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Async Steps", steps=[step1, step2])
    step_input = StepInput(input="direct async test")

    result = await steps.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Step1: direct async test")
    assert find_content_in_steps(result, "Step2: Step1: direct async test")


@pytest.mark.asyncio
async def test_steps_direct_aexecute_with_callable_class():
    """Test Steps.aexecute() directly without workflow."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=AsyncStepClassWithCallable())

    steps = Steps(name="Direct Async Steps", steps=[step1, step2])
    step_input = StepInput(input="direct async test")

    result = await steps.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Step1: direct async test")
    assert find_content_in_steps(result, "AsyncStepClassWithCallable: direct async test")


def test_steps_direct_execute_stream():
    """Test Steps.execute_stream() directly without workflow."""
    from agno.run.workflow import WorkflowRunOutput

    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps = Steps(name="Direct Stream Steps", steps=[step1, step2])
    step_input = StepInput(input="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(steps.execute_stream(step_input, mock_response, stream_events=True))

    # Should have started, completed events and final step output
    started_events = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 1  # Now returns single container StepOutput
    assert started_events[0].steps_count == 2


def test_steps_direct_empty():
    """Test Steps with no internal steps."""
    steps = Steps(name="Empty Steps", steps=[])
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert "No steps to execute" in result.content


def test_steps_direct_single_step():
    """Test Steps with single step."""
    step1 = Step(name="step1", executor=step1_function)
    steps = Steps(name="Single Step", steps=[step1])
    step_input = StepInput(input="single test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 1
    assert find_content_in_steps(result, "Step1: single test")


def test_steps_direct_chaining():
    """Test Steps properly chains outputs."""
    step1 = Step(name="first", executor=lambda x: StepOutput(content="first_output"))
    step2 = Step(name="second", executor=lambda x: StepOutput(content=f"second_{x.previous_step_content}"))
    step3 = Step(name="third", executor=lambda x: StepOutput(content=f"third_{x.previous_step_content}"))

    steps = Steps(name="Chaining Steps", steps=[step1, step2, step3])
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 3
    assert result.steps[0].content == "first_output"
    assert result.steps[1].content == "second_first_output"
    assert result.steps[2].content == "third_second_first_output"


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_steps_execution(shared_db):
    """Test basic Steps execution - sync non-streaming."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps_sequence = Steps(name="test_steps", steps=[step1, step2])

    workflow = Workflow(
        name="Basic Steps Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    response = workflow.run(input="test message")

    assert len(response.step_results) == 1
    assert find_content_in_steps(response.step_results[0], "Step2: Step1: test message")


def test_steps_streaming(shared_db):
    """Test Steps execution - sync streaming."""
    step1 = Step(name="step1", executor=step1_function)
    step2 = Step(name="step2", executor=step2_function)

    steps_sequence = Steps(name="streaming_steps", steps=[step1, step2])

    workflow = Workflow(
        name="Streaming Steps Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    events = list(workflow.run(input="stream test", stream=True, stream_events=True))

    # Check for required events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(steps_started) == 1
    assert len(steps_completed) == 1
    assert len(workflow_completed) == 1

    # Check final content
    final_response = workflow_completed[0]
    assert find_content_in_steps(final_response.step_results[0], "Step2: Step1: stream test")


@pytest.mark.asyncio
async def test_async_steps_execution(shared_db):
    """Test Steps execution - async non-streaming."""
    async_step = Step(name="async_step", executor=async_step_function)
    regular_step = Step(name="regular_step", executor=step2_function)

    steps_sequence = Steps(name="async_steps", steps=[async_step, regular_step])

    workflow = Workflow(
        name="Async Steps Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    response = await workflow.arun(input="async test")

    assert len(response.step_results) == 1
    assert find_content_in_steps(response.step_results[0], "Step2: AsyncStep: async test")


@pytest.mark.asyncio
async def test_async_steps_streaming(shared_db):
    """Test Steps execution - async streaming."""
    async_streaming_step = Step(name="async_streaming", executor=async_streaming_function)
    regular_step = Step(name="regular_step", executor=step2_function)

    steps_sequence = Steps(name="async_streaming_steps", steps=[async_streaming_step, regular_step])

    workflow = Workflow(
        name="Async Streaming Steps Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    events = []
    async for event in workflow.arun(input="async stream test", stream=True, stream_events=True):
        events.append(event)

    # Check that we have events
    assert len(events) > 0

    # Check for workflow completion
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_steps_chaining(shared_db):
    """Test that steps properly chain outputs."""
    step1 = Step(name="first", executor=lambda x: StepOutput(content="first_output"))
    step2 = Step(name="second", executor=lambda x: StepOutput(content=f"second_{x.previous_step_content}"))
    step3 = Step(name="third", executor=lambda x: StepOutput(content=f"third_{x.previous_step_content}"))

    steps_sequence = Steps(name="chaining_steps", steps=[step1, step2, step3])

    workflow = Workflow(
        name="Chaining Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    response = workflow.run(input="test")

    # Should chain through all steps
    assert find_content_in_steps(response.step_results[0], "third_second_first_output")


def test_empty_steps(shared_db):
    """Test Steps with no internal steps."""
    empty_steps = Steps(name="empty_steps", steps=[])

    workflow = Workflow(
        name="Empty Steps Test",
        db=shared_db,
        steps=[empty_steps],
    )

    response = workflow.run(input="test")

    assert "No steps to execute" in response.content


def test_steps_media_aggregation(shared_db):
    """Test Steps media aggregation."""
    step1 = Step(name="step1", executor=lambda x: StepOutput(content="content1", images=["image1.jpg"]))
    step2 = Step(name="step2", executor=lambda x: StepOutput(content="content2", videos=["video1.mp4"]))
    step3 = Step(name="step3", executor=lambda x: StepOutput(content="content3", audio=["audio1.mp3"]))

    steps_sequence = Steps(name="media_steps", steps=[step1, step2, step3])

    workflow = Workflow(
        name="Media Test",
        db=shared_db,
        steps=[steps_sequence],
    )

    response = workflow.run(input="test")

    # The media should be in the nested steps
    steps_container = response.step_results[0]
    assert steps_container.steps[0].images == ["image1.jpg"]
    assert steps_container.steps[1].videos == ["video1.mp4"]
    assert steps_container.steps[2].audio == ["audio1.mp3"]

    # Content should be from the Steps container (summary)
    assert find_content_in_steps(response.step_results[0], "content3")


def test_nested_steps(shared_db):
    """Test nested Steps."""
    inner_step1 = Step(name="inner1", executor=lambda x: StepOutput(content="inner1"))
    inner_step2 = Step(name="inner2", executor=lambda x: StepOutput(content=f"inner2_{x.previous_step_content}"))

    inner_steps = Steps(name="inner_steps", steps=[inner_step1, inner_step2])
    outer_step = Step(name="outer", executor=lambda x: StepOutput(content=f"outer_{x.previous_step_content}"))

    outer_steps = Steps(name="outer_steps", steps=[inner_steps, outer_step])

    workflow = Workflow(
        name="Nested Test",
        db=shared_db,
        steps=[outer_steps],
    )

    response = workflow.run(input="test")

    outer_steps_container = response.step_results[0]
    outer_step_result = outer_steps_container.steps[1]  # The outer step

    # New behavior: outer step receives deepest content from inner_steps ("inner2_inner1")
    assert outer_step_result.content == "outer_inner2_inner1"

    # Inner steps still contain their nested outputs
    assert find_content_in_steps(outer_steps_container.steps[0], "inner2_inner1")


def test_steps_with_other_workflow_steps(shared_db):
    """Test Steps in workflow with other steps."""
    individual_step = Step(name="individual", executor=lambda x: StepOutput(content="individual_output"))

    step1 = Step(name="grouped1", executor=lambda x: StepOutput(content=f"grouped1_{x.previous_step_content}"))
    step2 = Step(name="grouped2", executor=lambda x: StepOutput(content=f"grouped2_{x.previous_step_content}"))
    grouped_steps = Steps(name="grouped_steps", steps=[step1, step2])

    final_step = Step(name="final", executor=lambda x: StepOutput(content=f"final_{x.previous_step_content}"))

    workflow = Workflow(
        name="Mixed Workflow",
        db=shared_db,
        steps=[individual_step, grouped_steps, final_step],
    )

    response = workflow.run(input="test")

    assert len(response.step_results) == 3

    # New behavior: final step receives deepest content from grouped_steps
    final_step_result = response.step_results[2]
    assert final_step_result.content == "final_grouped2_grouped1_individual_output"

    # Grouped container still carries nested results
    grouped_steps_container = response.step_results[1]
    assert find_content_in_steps(grouped_steps_container, "grouped2_grouped1_individual_output")


# ============================================================================
# EARLY TERMINATION / STOP PROPAGATION TESTS
# ============================================================================


def early_stop_step(step_input: StepInput) -> StepOutput:
    """Step that requests early termination."""
    return StepOutput(
        content="Early stop requested",
        success=True,
        stop=True,
    )


def should_not_run_step(step_input: StepInput) -> StepOutput:
    """Step that should not run after early stop."""
    return StepOutput(
        content="This step should not have run",
        success=True,
    )


def normal_step(step_input: StepInput) -> StepOutput:
    """Normal step that doesn't request stop."""
    return StepOutput(
        content="Normal step output",
        success=True,
    )


def test_steps_propagates_stop_flag():
    """Test that Steps propagates stop flag from inner steps."""
    step1 = Step(name="normal", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)

    steps = Steps(
        name="Stop Steps",
        steps=[step1, step2],
    )
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Steps should propagate stop=True from inner step"


def test_steps_stop_propagation_in_workflow(shared_db):
    """Test that workflow stops when Steps' inner step returns stop=True."""
    step1 = Step(name="normal", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)

    workflow = Workflow(
        name="Steps Stop Propagation Test",
        db=shared_db,
        steps=[
            Steps(
                name="stop_steps",
                steps=[step1, step2],
            ),
            should_not_run_step,  # This should NOT execute
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # Should only have 1 step result (the Steps container), not 2
    assert len(response.step_results) == 1, "Workflow should stop after Steps with stop=True"
    assert response.step_results[0].stop is True


def test_steps_stops_inner_steps_on_stop_flag():
    """Test that Steps stops executing remaining inner steps when one returns stop=True."""
    step1 = Step(name="first", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)
    step3 = Step(name="should_not_run", executor=should_not_run_step)

    steps = Steps(
        name="Inner Stop Steps",
        steps=[step1, step2, step3],
    )
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    # Should only have 2 step results (first and stop_step), not 3
    assert len(result.steps) == 2, "Steps should stop after inner step with stop=True"
    assert result.steps[0].content == "Normal step output"
    assert result.steps[1].content == "Early stop requested"


def test_steps_streaming_propagates_stop(shared_db):
    """Test that streaming Steps propagates stop flag and stops workflow."""
    step1 = Step(name="normal", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)

    workflow = Workflow(
        name="Streaming Steps Stop Test",
        db=shared_db,
        steps=[
            Steps(
                name="stop_steps",
                steps=[step1, step2],
            ),
            should_not_run_step,
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Verify that the Steps completed with stop propagation
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    assert len(steps_completed) == 1

    # Check that inner step has stop=True in results
    step_results = steps_completed[0].step_results or []
    assert len(step_results) == 2
    assert step_results[1].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


@pytest.mark.asyncio
async def test_async_steps_propagates_stop():
    """Test that async Steps propagates stop flag."""
    step1 = Step(name="normal", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)

    steps = Steps(
        name="Async Stop Steps",
        steps=[step1, step2],
    )
    step_input = StepInput(input="test")

    result = await steps.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Async Steps should propagate stop=True from inner step"


@pytest.mark.asyncio
async def test_async_steps_streaming_propagates_stop(shared_db):
    """Test that async streaming Steps propagates stop flag and stops workflow."""
    step1 = Step(name="normal", executor=normal_step)
    step2 = Step(name="stop_step", executor=early_stop_step)

    workflow = Workflow(
        name="Async Streaming Steps Stop Test",
        db=shared_db,
        steps=[
            Steps(
                name="stop_steps",
                steps=[step1, step2],
            ),
            should_not_run_step,
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Verify that the Steps completed with stop propagation
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    assert len(steps_completed) == 1

    # Check that inner step has stop=True in results
    step_results = steps_completed[0].step_results or []
    assert len(step_results) == 2
    assert step_results[1].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


def test_steps_first_step_stops():
    """Test Steps when first step requests stop."""
    step1 = Step(name="stop_first", executor=early_stop_step)
    step2 = Step(name="should_not_run", executor=should_not_run_step)

    steps = Steps(
        name="First Stop Steps",
        steps=[step1, step2],
    )
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    # Should only have 1 step result
    assert len(result.steps) == 1, "Steps should stop after first step with stop=True"
    assert result.steps[0].content == "Early stop requested"


def test_steps_no_stop():
    """Test Steps when no inner steps request stop."""
    step1 = Step(name="first", executor=normal_step)
    step2 = Step(name="second", executor=step2_function)

    steps = Steps(
        name="No Stop Steps",
        steps=[step1, step2],
    )
    step_input = StepInput(input="test")

    result = steps.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is False, "Steps should not set stop when no inner step requests it"
    assert len(result.steps) == 2

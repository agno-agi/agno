"""Integration tests for Loop functionality in workflows."""

import pytest

from agno.run.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Loop, Parallel, Workflow
from agno.workflow.cel import CEL_AVAILABLE
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


# ============================================================================
# EARLY TERMINATION / STOP PROPAGATION TESTS
# ============================================================================


def early_stop_step(step_input: StepInput) -> StepOutput:
    """Step that requests early termination."""
    return StepOutput(
        step_name="early_stop",
        content="Early stop requested",
        success=True,
        stop=True,
    )


def should_not_run_step(step_input: StepInput) -> StepOutput:
    """Step that should not run after early stop."""
    return StepOutput(
        step_name="should_not_run",
        content="This step should not have run",
        success=True,
    )


def normal_loop_step(step_input: StepInput) -> StepOutput:
    """Normal step for loop testing."""
    return StepOutput(
        step_name="normal_loop_step",
        content="Normal loop iteration",
        success=True,
    )


def test_loop_propagates_stop_flag():
    """Test that Loop propagates stop flag from inner steps."""

    def never_end(outputs):
        return False  # Never end normally

    loop = Loop(
        name="Stop Loop",
        steps=[early_stop_step],
        end_condition=never_end,
        max_iterations=5,
    )
    step_input = StepInput(input="test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Loop should propagate stop=True from inner step"
    # Should only have 1 iteration since stop was requested
    assert len(result.steps) == 1, "Loop should stop after first iteration with stop=True"


def test_loop_stop_propagation_in_workflow(shared_db):
    """Test that workflow stops when Loop's inner step returns stop=True."""

    def never_end(outputs):
        return False

    workflow = Workflow(
        name="Loop Stop Propagation Test",
        db=shared_db,
        steps=[
            Loop(
                name="stop_loop",
                steps=[early_stop_step],
                end_condition=never_end,
                max_iterations=5,
            ),
            should_not_run_step,  # This should NOT execute
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # Should only have 1 step result (the Loop), not 2
    assert len(response.step_results) == 1, "Workflow should stop after Loop with stop=True"
    assert response.step_results[0].stop is True


def test_loop_stops_iterations_on_stop_flag():
    """Test that Loop stops iterating when a step returns stop=True."""
    iteration_count = [0]

    def counting_step(step_input: StepInput) -> StepOutput:
        iteration_count[0] += 1
        if iteration_count[0] >= 2:
            return StepOutput(
                step_name="counting_step",
                content=f"Iteration {iteration_count[0]} - stopping",
                success=True,
                stop=True,
            )
        return StepOutput(
            step_name="counting_step",
            content=f"Iteration {iteration_count[0]}",
            success=True,
        )

    def never_end(outputs):
        return False

    loop = Loop(
        name="Counting Loop",
        steps=[counting_step],
        end_condition=never_end,
        max_iterations=10,
    )
    step_input = StepInput(input="test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    # Should have stopped at iteration 2
    assert len(result.steps) == 2, "Loop should stop after iteration that returned stop=True"
    assert iteration_count[0] == 2


def test_loop_streaming_propagates_stop(shared_db):
    """Test that streaming Loop propagates stop flag and stops workflow."""

    def never_end(outputs):
        return False

    workflow = Workflow(
        name="Streaming Loop Stop Test",
        db=shared_db,
        steps=[
            Loop(
                name="stop_loop",
                steps=[early_stop_step],
                end_condition=never_end,
                max_iterations=5,
            ),
            should_not_run_step,
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Verify workflow completed
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(workflow_completed) == 1

    # Should only have 1 step result (the Loop), not 2
    assert len(workflow_completed[0].step_results) == 1, "Workflow should stop after Loop with stop=True"

    # Check that the loop output has stop=True
    loop_output = workflow_completed[0].step_results[0]
    assert loop_output.stop is True

    # Check that inner step has stop=True in results
    assert len(loop_output.steps) == 1
    assert loop_output.steps[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


@pytest.mark.asyncio
async def test_async_loop_propagates_stop():
    """Test that async Loop propagates stop flag."""

    def never_end(outputs):
        return False

    loop = Loop(
        name="Async Stop Loop",
        steps=[early_stop_step],
        end_condition=never_end,
        max_iterations=5,
    )
    step_input = StepInput(input="test")

    result = await loop.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Async Loop should propagate stop=True from inner step"
    assert len(result.steps) == 1, "Loop should stop after first iteration with stop=True"


@pytest.mark.asyncio
async def test_async_loop_streaming_propagates_stop(shared_db):
    """Test that async streaming Loop propagates stop flag and stops workflow."""

    def never_end(outputs):
        return False

    workflow = Workflow(
        name="Async Streaming Loop Stop Test",
        db=shared_db,
        steps=[
            Loop(
                name="stop_loop",
                steps=[early_stop_step],
                end_condition=never_end,
                max_iterations=5,
            ),
            should_not_run_step,
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Verify workflow completed
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(workflow_completed) == 1

    # Should only have 1 step result (the Loop), not 2
    assert len(workflow_completed[0].step_results) == 1, "Workflow should stop after Loop with stop=True"

    # Check that the loop output has stop=True
    loop_output = workflow_completed[0].step_results[0]
    assert loop_output.stop is True

    # Check that inner step has stop=True in results
    assert len(loop_output.steps) == 1
    assert loop_output.steps[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


def test_loop_with_multiple_steps_propagates_stop():
    """Test Loop with multiple steps per iteration propagates stop from any step."""

    def first_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="first", content="First step done", success=True)

    def second_step_stops(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="second", content="Second step stops", success=True, stop=True)

    def third_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="third", content="Third step - should not run", success=True)

    def never_end(outputs):
        return False

    loop = Loop(
        name="Multi Step Stop Loop",
        steps=[first_step, second_step_stops, third_step],
        end_condition=never_end,
        max_iterations=5,
    )
    step_input = StepInput(input="test")

    result = loop.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    # Should have first and second step from first iteration only
    assert len(result.steps) == 2, "Loop should stop after step that returned stop=True"
    assert result.steps[0].content == "First step done"
    assert result.steps[1].content == "Second step stops"


# ============================================================================
# CEL EXPRESSION TESTS
# ============================================================================


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_iteration_count():
    """Test CEL loop with current_iteration end condition."""
    loop = Loop(
        name="CEL Iteration Loop",
        steps=[research_step],
        end_condition="current_iteration >= 2",
        max_iterations=5,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    # current_iteration is incremented AFTER each iteration completes, THEN end_condition is checked
    # So current_iteration >= 2 is True after iteration 1 completes (when current_iteration becomes 2)
    assert len(result.steps) == 2


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_max_iterations_expression():
    """Test CEL loop comparing current_iteration to max_iterations."""
    loop = Loop(
        name="CEL Max Iterations Loop",
        steps=[research_step],
        end_condition="current_iteration >= max_iterations - 1",
        max_iterations=3,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    # max_iterations=3, so end_condition is "current_iteration >= 2"
    assert len(result.steps) == 2


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_last_step_content():
    """Test CEL loop checking last_step_content."""
    iteration_counter = [0]

    def counting_step(step_input: StepInput) -> StepOutput:
        iteration_counter[0] += 1
        content = "DONE" if iteration_counter[0] >= 3 else f"Iteration {iteration_counter[0]}"
        return StepOutput(step_name="counting", content=content, success=True)

    loop = Loop(
        name="CEL Last Content Loop",
        steps=[counting_step],
        end_condition='last_step_content.contains("DONE")',
        max_iterations=10,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 3
    assert "DONE" in result.steps[-1].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_all_success():
    """Test CEL loop with all_success check."""

    def always_success_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="success", content="Success", success=True)

    loop = Loop(
        name="CEL All Success Loop",
        steps=[always_success_step],
        end_condition="all_success && current_iteration >= 2",
        max_iterations=10,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    assert all(s.success for s in result.steps)
    assert len(result.steps) == 2


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_step_outputs():
    """Test CEL loop with step_outputs map variable."""
    loop = Loop(
        name="CEL Step Outputs Loop",
        steps=[research_step, analysis_step],  # 2 steps per iteration
        end_condition="step_outputs.size() >= 2 && all_success",
        max_iterations=10,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    # step_outputs has 2 entries per iteration, so stops after first iteration
    assert len(result.steps) == 2


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_in_workflow(shared_db):
    """Test CEL loop within a workflow."""
    workflow = Workflow(
        name="CEL Loop Workflow",
        db=shared_db,
        steps=[
            Loop(
                name="cel_loop",
                steps=[research_step],
                end_condition="current_iteration >= 2",
                max_iterations=5,
            )
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    loop_output = response.step_results[0]
    assert len(loop_output.steps) == 2


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_streaming(shared_db):
    """Test CEL loop with streaming."""
    workflow = Workflow(
        name="CEL Streaming Loop",
        db=shared_db,
        steps=[
            Loop(
                name="cel_stream_loop",
                steps=[research_step],
                end_condition="current_iteration >= 1",
                max_iterations=5,
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
@pytest.mark.asyncio
async def test_cel_loop_async():
    """Test CEL loop with async execution."""
    loop = Loop(
        name="CEL Async Loop",
        steps=[research_step],
        end_condition="current_iteration >= 1",
        max_iterations=5,
    )

    result = await loop.aexecute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 1


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_loop_compound_condition():
    """Test CEL loop with compound end condition."""
    loop = Loop(
        name="CEL Compound Loop",
        steps=[research_step],
        end_condition="current_iteration >= 2 && all_success",
        max_iterations=10,
    )

    result = loop.execute(StepInput(input="test"))

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert all(s.success for s in result.steps)

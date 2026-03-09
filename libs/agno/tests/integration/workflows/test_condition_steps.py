"""Integration tests for Condition functionality in workflows."""

import pytest

from agno.run.base import RunStatus
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Condition, Parallel, Workflow
from agno.workflow.cel import CEL_AVAILABLE
from agno.workflow.types import StepInput, StepOutput


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step that generates content."""
    return StepOutput(content=f"Research findings: {step_input.input}. Found data showing 40% growth.", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(content=f"Analysis of research: {step_input.previous_step_content}", success=True)


def fact_check_step(step_input: StepInput) -> StepOutput:
    """Fact checking step."""
    return StepOutput(content="Fact check complete: All statistics verified.", success=True)


# Condition evaluators
def has_statistics(step_input: StepInput) -> bool:
    """Check if content contains statistics."""
    content = step_input.previous_step_content or step_input.input or ""
    # Only check the input message for statistics
    content = step_input.input or ""
    return any(x in content.lower() for x in ["percent", "%", "growth", "increase", "decrease"])


def is_tech_topic(step_input: StepInput) -> bool:
    """Check if topic is tech-related."""
    content = step_input.input or step_input.previous_step_content or ""
    return any(x in content.lower() for x in ["ai", "tech", "software", "data"])


async def async_evaluator(step_input: StepInput) -> bool:
    """Async evaluator."""
    return is_tech_topic(step_input)


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_condition_direct_execute_true():
    """Test Condition.execute() directly when condition is true."""
    condition = Condition(name="Direct True Condition", evaluator=has_statistics, steps=[fact_check_step])
    step_input = StepInput(input="Market shows 40% growth")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 1
    assert "Fact check complete" in result.steps[0].content


def test_condition_direct_execute_false():
    """Test Condition.execute() directly when condition is false."""
    condition = Condition(name="Direct False Condition", evaluator=has_statistics, steps=[fact_check_step])
    step_input = StepInput(input="General market overview")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.steps is None or len(result.steps) == 0  # No steps executed


def test_condition_direct_boolean_evaluator():
    """Test Condition with boolean evaluator."""
    condition = Condition(name="Boolean Condition", evaluator=True, steps=[research_step])
    step_input = StepInput(input="test")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 1
    assert "Research findings" in result.steps[0].content


@pytest.mark.asyncio
async def test_condition_direct_aexecute():
    """Test Condition.aexecute() directly."""
    condition = Condition(name="Direct Async Condition", evaluator=async_evaluator, steps=[research_step])
    step_input = StepInput(input="AI technology")

    result = await condition.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 1
    assert "Research findings" in result.steps[0].content


def test_condition_direct_execute_stream():
    """Test Condition.execute_stream() directly."""
    from agno.run.workflow import WorkflowRunOutput

    condition = Condition(name="Direct Stream Condition", evaluator=is_tech_topic, steps=[research_step])
    step_input = StepInput(input="AI trends")

    # Mock workflow response for streaming
    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(condition.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))

    # Should have started, completed events and step outputs
    started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 1
    assert started_events[0].condition_result is True


def test_condition_direct_multiple_steps():
    """Test Condition with multiple steps."""
    condition = Condition(name="Multi Step Condition", evaluator=is_tech_topic, steps=[research_step, analysis_step])
    step_input = StepInput(input="AI technology")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert len(result.steps) == 2
    assert "Research findings" in result.steps[0].content
    assert "Analysis of research" in result.steps[1].content


# ============================================================================
# EXISTING INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_condition_true(shared_db):
    """Test basic condition that evaluates to True."""
    workflow = Workflow(
        name="Basic Condition",
        db=shared_db,
        steps=[research_step, Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step])],
    )

    response = workflow.run(input="Market shows 40% growth")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2
    # Condition output is a list
    assert isinstance(response.step_results[1], StepOutput)
    # One step executed in condition
    assert len(response.step_results[1].steps) == 1
    assert "Fact check complete" in response.step_results[1].steps[0].content


def test_basic_condition_false(shared_db):
    """Test basic condition that evaluates to False."""
    workflow = Workflow(
        name="Basic Condition False",
        db=shared_db,
        steps=[research_step, Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step])],
    )

    # Using a message without statistics
    response = workflow.run(input="General market overview")
    assert isinstance(response, WorkflowRunOutput)

    # Should have 2 step responses: research_step + condition result
    assert len(response.step_results) == 2
    assert isinstance(response.step_results[1], StepOutput)
    assert (
        response.step_results[1].steps is None or len(response.step_results[1].steps) == 0
    )  # No steps executed when condition is false
    assert "not met" in response.step_results[1].content


def test_parallel_with_conditions(shared_db):
    """Test parallel containing multiple conditions."""
    workflow = Workflow(
        name="Parallel with Conditions",
        db=shared_db,
        steps=[
            research_step,  # Add a step before parallel to ensure proper chaining
            Parallel(
                Condition(name="tech_check", evaluator=is_tech_topic, steps=[analysis_step]),
                Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step]),
                name="parallel_conditions",
            ),
        ],
    )

    response = workflow.run(input="AI market shows 40% growth")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2  # research_step + parallel

    # Check the parallel output structure
    parallel_output = response.step_results[1]

    # Check that the parallel step has nested condition results
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2  # Two conditions executed

    # Check that we can access the nested step content
    condition_results = parallel_output.steps
    tech_condition = next((step for step in condition_results if step.step_name == "tech_check"), None)
    stats_condition = next((step for step in condition_results if step.step_name == "stats_check"), None)

    assert tech_condition is not None
    assert stats_condition is not None
    assert len(tech_condition.steps) == 1  # analysis_step executed
    assert len(stats_condition.steps) == 1  # fact_check_step executed
    assert "Analysis of research" in tech_condition.steps[0].content
    assert "Fact check complete" in stats_condition.steps[0].content


def test_condition_streaming(shared_db):
    """Test condition with streaming."""
    workflow = Workflow(
        name="Streaming Condition",
        db=shared_db,
        steps=[Condition(name="tech_check", evaluator=is_tech_topic, steps=[research_step, analysis_step])],
    )

    events = list(workflow.run(input="AI trends", stream=True, stream_events=True))

    # Verify event types
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert len(workflow_completed) == 1
    assert condition_started[0].condition_result is True


def test_condition_error_handling(shared_db):
    """Test condition error handling."""

    def failing_evaluator(_: StepInput) -> bool:
        raise ValueError("Evaluator failed")

    workflow = Workflow(
        name="Error Condition",
        db=shared_db,
        steps=[Condition(name="failing_check", evaluator=failing_evaluator, steps=[research_step])],
    )

    with pytest.raises(ValueError):
        response = workflow.run(input="test")

    response = workflow.get_last_run_output()
    assert isinstance(response, WorkflowRunOutput)
    assert response.status == RunStatus.error
    assert "Evaluator failed" in response.content


def test_nested_conditions(shared_db):
    """Test nested conditions."""
    workflow = Workflow(
        name="Nested Conditions",
        db=shared_db,
        steps=[
            Condition(
                name="outer",
                evaluator=is_tech_topic,
                steps=[research_step, Condition(name="inner", evaluator=has_statistics, steps=[fact_check_step])],
            )
        ],
    )

    response = workflow.run(input="AI market shows 40% growth")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    outer_condition = response.step_results[0]
    assert isinstance(outer_condition, StepOutput)
    # research_step + inner condition result
    assert len(outer_condition.steps) == 2

    # Check that the inner condition is properly nested
    inner_condition = outer_condition.steps[1]  # Second step should be the inner condition
    assert inner_condition.step_type == "Condition"
    assert inner_condition.step_name == "inner"
    assert len(inner_condition.steps) == 1  # fact_check_step executed
    assert "Fact check complete" in inner_condition.steps[0].content


@pytest.mark.asyncio
async def test_async_condition(shared_db):
    """Test async condition."""
    workflow = Workflow(
        name="Async Condition",
        db=shared_db,
        steps=[Condition(name="async_check", evaluator=async_evaluator, steps=[research_step])],
    )

    response = await workflow.arun(input="AI technology")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1
    assert isinstance(response.step_results[0], StepOutput)
    assert len(response.step_results[0].steps) == 1
    assert "Research findings" in response.step_results[0].steps[0].content


@pytest.mark.asyncio
async def test_async_condition_streaming(shared_db):
    """Test async condition with streaming."""
    workflow = Workflow(
        name="Async Streaming Condition",
        db=shared_db,
        steps=[Condition(name="async_check", evaluator=async_evaluator, steps=[research_step])],
    )

    events = []
    async for event in workflow.arun(input="AI technology", stream=True, stream_events=True):
        events.append(event)

    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert len(workflow_completed) == 1
    assert condition_started[0].condition_result is True


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


def test_condition_propagates_stop_flag():
    """Test that Condition propagates stop flag from inner steps to workflow."""
    condition = Condition(
        name="Stop Condition",
        evaluator=True,
        steps=[early_stop_step],
    )
    step_input = StepInput(input="test")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Condition should propagate stop=True from inner step"


def test_condition_stop_propagation_in_workflow(shared_db):
    """Test that workflow stops when Condition's inner step returns stop=True."""
    workflow = Workflow(
        name="Stop Propagation Test",
        db=shared_db,
        steps=[
            Condition(
                name="stop_condition",
                evaluator=True,
                steps=[early_stop_step],
            ),
            should_not_run_step,  # This should NOT execute
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # Should only have 1 step result (the Condition), not 2
    assert len(response.step_results) == 1, "Workflow should stop after Condition with stop=True"
    assert response.step_results[0].stop is True


def test_condition_streaming_propagates_stop(shared_db):
    """Test that streaming Condition propagates stop flag and stops workflow."""
    workflow = Workflow(
        name="Streaming Stop Test",
        db=shared_db,
        steps=[
            Condition(
                name="stop_condition",
                evaluator=True,
                steps=[early_stop_step],
            ),
            should_not_run_step,
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Verify that the Condition completed with stop propagation
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    assert len(condition_completed) == 1

    # Check that inner step has stop=True in results
    step_results = condition_completed[0].step_results or []
    assert len(step_results) == 1
    assert step_results[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    # by checking there's no StepStartedEvent/StepCompletedEvent for it
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


@pytest.mark.asyncio
async def test_async_condition_propagates_stop():
    """Test that async Condition propagates stop flag."""
    condition = Condition(
        name="Async Stop Condition",
        evaluator=True,
        steps=[early_stop_step],
    )
    step_input = StepInput(input="test")

    result = await condition.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Async Condition should propagate stop=True from inner step"


@pytest.mark.asyncio
async def test_async_condition_streaming_propagates_stop(shared_db):
    """Test that async streaming Condition propagates stop flag and stops workflow."""
    workflow = Workflow(
        name="Async Streaming Stop Test",
        db=shared_db,
        steps=[
            Condition(
                name="stop_condition",
                evaluator=True,
                steps=[early_stop_step],
            ),
            should_not_run_step,
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Verify that the Condition completed with stop propagation
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    assert len(condition_completed) == 1

    # Check that inner step has stop=True in results
    step_results = condition_completed[0].step_results or []
    assert len(step_results) == 1
    assert step_results[0].stop is True

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


# ============================================================================
# ELSE_STEPS TESTS
# ============================================================================


def general_step(step_input: StepInput) -> StepOutput:
    """General research step (else branch)."""
    return StepOutput(content=f"General research: {step_input.input}", success=True)


def fallback_step(step_input: StepInput) -> StepOutput:
    """Fallback step for else branch."""
    return StepOutput(content="Fallback step executed", success=True)


def test_condition_else_steps_execute_when_false():
    """Test that else_steps execute when condition is False."""
    condition = Condition(
        name="Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[general_step],
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.success is True
    assert len(result.steps) == 1
    assert "General research" in result.steps[0].content
    assert "else branch" in result.content


def test_condition_else_steps_not_executed_when_true():
    """Test that else_steps are NOT executed when condition is True."""
    condition = Condition(
        name="Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[general_step],
    )
    step_input = StepInput(input="AI technology trends")  # Tech topic

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.success is True
    assert len(result.steps) == 1
    assert "Research findings" in result.steps[0].content
    assert "if branch" in result.content


def test_condition_no_else_steps_returns_not_met():
    """Test that without else_steps, condition returns 'not met' when False."""
    condition = Condition(
        name="Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        # No else_steps
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.success is True
    assert result.steps is None or len(result.steps) == 0
    assert "not met" in result.content


def test_condition_empty_else_steps_treated_as_none():
    """Test that empty else_steps list is treated as None."""
    condition = Condition(
        name="Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[],  # Empty list should be treated as None
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.steps is None or len(result.steps) == 0
    assert "not met" in result.content


def test_condition_else_steps_multiple_steps():
    """Test else_steps with multiple steps and chaining."""
    condition = Condition(
        name="Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[general_step, analysis_step],  # Multiple else steps
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.success is True
    assert len(result.steps) == 2
    assert "General research" in result.steps[0].content
    assert "Analysis" in result.steps[1].content
    assert "else branch" in result.content


@pytest.mark.asyncio
async def test_condition_else_steps_aexecute():
    """Test else_steps with async execution."""
    condition = Condition(
        name="Async Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[general_step],
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    result = await condition.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.success is True
    assert len(result.steps) == 1
    assert "General research" in result.steps[0].content
    assert "else branch" in result.content


def test_condition_else_steps_streaming():
    """Test else_steps with streaming."""
    from agno.run.workflow import WorkflowRunOutput

    condition = Condition(
        name="Stream Tech Check",
        evaluator=is_tech_topic,
        steps=[research_step],
        else_steps=[general_step],
    )
    step_input = StepInput(input="General market overview")  # Not tech topic

    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(condition.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))

    started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 1
    assert started_events[0].condition_result is False
    assert completed_events[0].branch == "else"


def test_condition_else_steps_stop_propagation():
    """Test that stop flag propagates correctly from else_steps."""
    condition = Condition(
        name="Stop in Else",
        evaluator=False,  # Boolean False to trigger else branch
        steps=[research_step],
        else_steps=[early_stop_step],
    )
    step_input = StepInput(input="test")

    result = condition.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Condition should propagate stop=True from else_steps"


def test_condition_else_steps_in_workflow(shared_db):
    """Test else_steps in a real workflow."""
    workflow = Workflow(
        name="Workflow with else_steps",
        db=shared_db,
        steps=[
            Condition(
                name="topic_router",
                evaluator=is_tech_topic,
                steps=[research_step],
                else_steps=[general_step, fallback_step],
            )
        ],
    )

    # Test with non-tech input (should trigger else branch)
    response = workflow.run(input="General market overview")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1

    condition_result = response.step_results[0]
    assert len(condition_result.steps) == 2  # general_step + fallback_step
    assert "General research" in condition_result.steps[0].content
    assert "Fallback step" in condition_result.steps[1].content


def test_condition_else_steps_in_workflow_if_branch(shared_db):
    """Test that if branch works correctly when else_steps is provided."""
    workflow = Workflow(
        name="Workflow with else_steps if branch",
        db=shared_db,
        steps=[
            Condition(
                name="topic_router",
                evaluator=is_tech_topic,
                steps=[research_step],
                else_steps=[general_step],
            )
        ],
    )

    # Test with tech input (should trigger if branch)
    response = workflow.run(input="AI technology trends")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 1

    condition_result = response.step_results[0]
    assert len(condition_result.steps) == 1
    assert "Research findings" in condition_result.steps[0].content
    assert "if branch" in condition_result.content


# ============================================================================
# CEL EXPRESSION TESTS
# ============================================================================


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_basic_input_contains():
    """Test CEL condition with input.contains() expression."""
    condition = Condition(
        name="CEL Input Contains",
        evaluator='input.contains("urgent")',
        steps=[research_step],
    )

    # Should trigger - contains "urgent"
    result_true = condition.execute(StepInput(input="This is an urgent request"))
    assert len(result_true.steps) == 1
    assert "Research findings" in result_true.steps[0].content

    # Should not trigger - no "urgent"
    result_false = condition.execute(StepInput(input="This is a normal request"))
    assert result_false.steps is None or len(result_false.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_previous_step_content():
    """Test CEL condition checking previous_step_content."""
    condition = Condition(
        name="CEL Previous Content",
        evaluator="previous_step_content.size() > 10",
        steps=[analysis_step],
    )

    # Should trigger - has previous content > 10 chars
    result_true = condition.execute(
        StepInput(input="test", previous_step_content="This is some longer content from previous step")
    )
    assert len(result_true.steps) == 1
    assert "Analysis" in result_true.steps[0].content

    # Should not trigger - short previous content
    result_false = condition.execute(StepInput(input="test", previous_step_content="Short"))
    assert result_false.steps is None or len(result_false.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_additional_data():
    """Test CEL condition with additional_data access."""
    condition = Condition(
        name="CEL Additional Data",
        evaluator='additional_data.priority == "high"',
        steps=[fact_check_step],
    )

    # Should trigger - high priority
    result_true = condition.execute(StepInput(input="test", additional_data={"priority": "high"}))
    assert len(result_true.steps) == 1

    # Should not trigger - low priority
    result_false = condition.execute(StepInput(input="test", additional_data={"priority": "low"}))
    assert result_false.steps is None or len(result_false.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_session_state():
    """Test CEL condition with session_state access."""
    condition = Condition(
        name="CEL Session State",
        evaluator="session_state.request_count > 5",
        steps=[research_step],
    )

    # Should trigger - count > 5
    result_true = condition.execute(StepInput(input="test"), session_state={"request_count": 10})
    assert len(result_true.steps) == 1

    # Should not trigger - count <= 5
    result_false = condition.execute(StepInput(input="test"), session_state={"request_count": 3})
    assert result_false.steps is None or len(result_false.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_compound_expression():
    """Test CEL condition with compound logical expression."""
    condition = Condition(
        name="CEL Compound",
        evaluator='input.contains("urgent") && additional_data.priority == "high"',
        steps=[fact_check_step],
    )

    # Should trigger - both conditions met
    result_true = condition.execute(StepInput(input="This is urgent", additional_data={"priority": "high"}))
    assert len(result_true.steps) == 1

    # Should not trigger - only one condition met
    result_partial = condition.execute(StepInput(input="This is urgent", additional_data={"priority": "low"}))
    assert result_partial.steps is None or len(result_partial.steps) == 0


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_with_else_steps():
    """Test CEL condition with else_steps."""

    # Define else step locally to avoid any scope issues
    def cel_else_step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Else branch: {step_input.input}", success=True)

    condition = Condition(
        name="CEL With Else",
        evaluator='input.contains("premium")',
        steps=[research_step],
        else_steps=[cel_else_step],
    )

    # Should trigger if branch
    result_if = condition.execute(StepInput(input="premium user request"))
    assert len(result_if.steps) == 1
    assert "Research findings" in result_if.steps[0].content
    assert "if branch" in result_if.content

    # Should trigger else branch
    result_else = condition.execute(StepInput(input="free user request"))
    assert len(result_else.steps) == 1
    assert "Else branch" in result_else.steps[0].content
    assert "else branch" in result_else.content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_in_workflow(shared_db):
    """Test CEL condition within a workflow."""
    workflow = Workflow(
        name="CEL Condition Workflow",
        db=shared_db,
        steps=[
            research_step,
            Condition(
                name="cel_check",
                evaluator='input.contains("AI")',
                steps=[analysis_step],
            ),
        ],
    )

    # Should trigger condition
    response = workflow.run(input="AI technology trends")
    assert len(response.step_results) == 2
    condition_result = response.step_results[1]
    assert len(condition_result.steps) == 1
    assert "Analysis" in condition_result.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_streaming(shared_db):
    """Test CEL condition with streaming."""
    workflow = Workflow(
        name="CEL Streaming Condition",
        db=shared_db,
        steps=[
            Condition(
                name="cel_stream",
                evaluator='input.contains("stream")',
                steps=[research_step],
            )
        ],
    )

    events = list(workflow.run(input="stream test", stream=True, stream_events=True))

    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert condition_started[0].condition_result is True


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
@pytest.mark.asyncio
async def test_cel_condition_async():
    """Test CEL condition with async execution."""
    condition = Condition(
        name="CEL Async",
        evaluator="input.size() > 5",
        steps=[research_step],
    )

    # Should trigger - input length > 5
    result = await condition.aexecute(StepInput(input="longer input text"))
    assert len(result.steps) == 1
    assert "Research findings" in result.steps[0].content


@pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
def test_cel_condition_previous_step_outputs():
    """Test CEL condition with previous_step_outputs map variable."""
    condition = Condition(
        name="CEL Previous Step Outputs",
        evaluator='previous_step_outputs.step1.contains("important")',
        steps=[fact_check_step],
    )

    from agno.workflow.types import StepOutput as SO

    # Should trigger - step1 contains "important"
    step_input = StepInput(
        input="test",
        previous_step_outputs={
            "step1": SO(content="This is important content", success=True),
            "step2": SO(content="Second step output", success=True),
        },
    )

    result = condition.execute(step_input)
    assert len(result.steps) == 1
    assert "Fact check" in result.steps[0].content

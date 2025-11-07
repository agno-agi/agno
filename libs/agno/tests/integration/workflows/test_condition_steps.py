"""Integration tests for Condition functionality in workflows."""

import pytest

from agno.run.base import RunStatus
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Condition, Parallel, Workflow
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

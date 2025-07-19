"""Integration tests for Condition functionality in workflows."""

import pytest

from agno.run.base import RunStatus
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.workflow.v2 import Condition, Parallel, Workflow
from agno.workflow.v2.types import StepInput, StepOutput


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step that generates content."""
    return StepOutput(content=f"Research findings: {step_input.message}. Found data showing 40% growth.", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(content=f"Analysis of research: {step_input.previous_step_content}", success=True)


def fact_check_step(step_input: StepInput) -> StepOutput:
    """Fact checking step."""
    return StepOutput(content="Fact check complete: All statistics verified.", success=True)


# Condition evaluators
def has_statistics(step_input: StepInput) -> bool:
    """Check if content contains statistics."""
    content = step_input.previous_step_content or step_input.message or ""
    # Only check the input message for statistics
    content = step_input.message or ""
    return any(x in content.lower() for x in ["percent", "%", "growth", "increase", "decrease"])


def is_tech_topic(step_input: StepInput) -> bool:
    """Check if topic is tech-related."""
    content = step_input.message or step_input.previous_step_content or ""
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
    step_input = StepInput(message="Market shows 40% growth")

    result = condition.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 1
    assert "Fact check complete" in result[0].content


def test_condition_direct_execute_false():
    """Test Condition.execute() directly when condition is false."""
    condition = Condition(name="Direct False Condition", evaluator=has_statistics, steps=[fact_check_step])
    step_input = StepInput(message="General market overview")

    result = condition.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 0  # No steps executed


def test_condition_direct_boolean_evaluator():
    """Test Condition with boolean evaluator."""
    condition = Condition(name="Boolean Condition", evaluator=True, steps=[research_step])
    step_input = StepInput(message="test")

    result = condition.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 1
    assert "Research findings" in result[0].content


@pytest.mark.asyncio
async def test_condition_direct_aexecute():
    """Test Condition.aexecute() directly."""
    condition = Condition(name="Direct Async Condition", evaluator=async_evaluator, steps=[research_step])
    step_input = StepInput(message="AI technology")

    result = await condition.aexecute(step_input)

    assert isinstance(result, list)
    assert len(result) == 1
    assert "Research findings" in result[0].content


def test_condition_direct_execute_stream():
    """Test Condition.execute_stream() directly."""
    from agno.run.v2.workflow import WorkflowRunResponse

    condition = Condition(name="Direct Stream Condition", evaluator=is_tech_topic, steps=[research_step])
    step_input = StepInput(message="AI trends")

    # Mock workflow response for streaming
    mock_response = WorkflowRunResponse(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(
        condition.execute_stream(step_input, workflow_run_response=mock_response, stream_intermediate_steps=True)
    )

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
    step_input = StepInput(message="AI technology")

    result = condition.execute(step_input)

    assert isinstance(result, list)
    assert len(result) == 2
    assert "Research findings" in result[0].content
    assert "Analysis of research" in result[1].content


# ============================================================================
# EXISTING INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_condition_true(workflow_storage):
    """Test basic condition that evaluates to True."""
    workflow = Workflow(
        name="Basic Condition",
        storage=workflow_storage,
        steps=[research_step, Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step])],
    )

    response = workflow.run(message="Market shows 40% growth")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2
    # Condition output is a list
    assert isinstance(response.step_responses[1], list)
    # One step executed in condition
    assert len(response.step_responses[1]) == 1
    assert "Fact check complete" in response.step_responses[1][0].content


def test_basic_condition_false(workflow_storage):
    """Test basic condition that evaluates to False."""
    workflow = Workflow(
        name="Basic Condition False",
        storage=workflow_storage,
        steps=[research_step, Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step])],
    )

    # Using a message without statistics
    response = workflow.run(message="General market overview")
    assert isinstance(response, WorkflowRunResponse)

    # Should have 2 step responses: research_step + empty condition result
    assert len(response.step_responses) == 2
    assert response.step_responses[1] == []  # Condition returned empty list


def test_parallel_with_conditions(workflow_storage):
    """Test parallel containing multiple conditions."""
    workflow = Workflow(
        name="Parallel with Conditions",
        storage=workflow_storage,
        steps=[
            research_step,  # Add a step before parallel to ensure proper chaining
            Parallel(
                Condition(name="tech_check", evaluator=is_tech_topic, steps=[analysis_step]),
                Condition(name="stats_check", evaluator=has_statistics, steps=[fact_check_step]),
                name="parallel_conditions",
            ),
        ],
    )

    response = workflow.run(message="AI market shows 40% growth")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2  # research_step + parallel

    # Check the parallel output structure
    parallel_output = response.step_responses[1]
    assert parallel_output.success is True
    assert "SUCCESS: analysis_step" in parallel_output.content
    assert "SUCCESS: fact_check_step" in parallel_output.content


def test_condition_streaming(workflow_storage):
    """Test condition with streaming."""
    workflow = Workflow(
        name="Streaming Condition",
        storage=workflow_storage,
        steps=[Condition(name="tech_check", evaluator=is_tech_topic, steps=[research_step, analysis_step])],
    )

    events = list(workflow.run(message="AI trends", stream=True, stream_intermediate_steps=True))

    # Verify event types
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert len(workflow_completed) == 1
    assert condition_started[0].condition_result is True


def test_condition_error_handling(workflow_storage):
    """Test condition error handling."""

    def failing_evaluator(_: StepInput) -> bool:
        raise ValueError("Evaluator failed")

    workflow = Workflow(
        name="Error Condition",
        storage=workflow_storage,
        steps=[Condition(name="failing_check", evaluator=failing_evaluator, steps=[research_step])],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert response.status == RunStatus.error
    assert "Evaluator failed" in response.content


def test_nested_conditions(workflow_storage):
    """Test nested conditions."""
    workflow = Workflow(
        name="Nested Conditions",
        storage=workflow_storage,
        steps=[
            Condition(
                name="outer",
                evaluator=is_tech_topic,
                steps=[research_step, Condition(name="inner", evaluator=has_statistics, steps=[fact_check_step])],
            )
        ],
    )

    response = workflow.run(message="AI market shows 40% growth")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    outer_condition = response.step_responses[0]
    assert isinstance(outer_condition, list)
    # research_step + inner condition result
    assert len(outer_condition) == 2


@pytest.mark.asyncio
async def test_async_condition(workflow_storage):
    """Test async condition."""
    workflow = Workflow(
        name="Async Condition",
        storage=workflow_storage,
        steps=[Condition(name="async_check", evaluator=async_evaluator, steps=[research_step])],
    )

    response = await workflow.arun(message="AI technology")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 1
    assert isinstance(response.step_responses[0], list)
    assert len(response.step_responses[0]) == 1


@pytest.mark.asyncio
async def test_async_condition_streaming(workflow_storage):
    """Test async condition with streaming."""
    workflow = Workflow(
        name="Async Streaming Condition",
        storage=workflow_storage,
        steps=[Condition(name="async_check", evaluator=async_evaluator, steps=[research_step])],
    )

    events = []
    async for event in await workflow.arun(message="AI technology", stream=True, stream_intermediate_steps=True):
        events.append(event)

    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert len(workflow_completed) == 1
    assert condition_started[0].condition_result is True

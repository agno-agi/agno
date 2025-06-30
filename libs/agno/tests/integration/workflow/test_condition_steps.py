"""Integration tests for Condition functionality in workflows."""

import pytest

from agno.run.base import RunStatus
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.storage.sqlite import SqliteStorage
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

    # The step_responses will be empty due to the error
    assert len(response.step_responses) == 0

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

    events = list(workflow.run(message="AI trends", stream=True))

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
    async for event in await workflow.arun(message="AI technology", stream=True):
        events.append(event)

    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert len(workflow_completed) == 1
    assert condition_started[0].condition_result is True

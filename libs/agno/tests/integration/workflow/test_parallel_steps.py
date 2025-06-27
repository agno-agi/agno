"""Integration tests for Parallel steps functionality."""

import pytest

from agno.agent import Agent
from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.storage.sqlite import SqliteStorage
from agno.workflow.v2 import Workflow
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput


# Simple step functions for testing
def step_a(step_input: StepInput) -> StepOutput:
    """Test step A."""
    return StepOutput(content="Output A")


def step_b(step_input: StepInput) -> StepOutput:
    """Test step B."""
    return StepOutput(content="Output B")


def final_step(step_input: StepInput) -> StepOutput:
    """Combine previous outputs."""
    return StepOutput(content=f"Final: {step_input.get_all_previous_content()}")


def test_basic_parallel(workflow_storage):
    """Test basic parallel execution."""
    workflow = Workflow(
        name="Basic Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2

    # Check parallel output
    parallel_output = response.step_responses[0]
    assert isinstance(parallel_output, StepOutput)
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content

def test_parallel_streaming(workflow_storage):
    """Test parallel execution with streaming."""
    workflow = Workflow(
        name="Streaming Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = list(workflow.run(message="test", stream=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

def test_parallel_with_agent(workflow_storage, test_agent):
    """Test parallel execution with agent step."""
    agent_step = Step(name="agent_step", agent=test_agent)

    workflow = Workflow(
        name="Agent Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, agent_step, name="Mixed Parallel"), final_step],
    )

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    parallel_output = response.step_responses[0]
    assert isinstance(parallel_output, StepOutput)
    assert "Output A" in parallel_output.content

@pytest.mark.asyncio
async def test_async_parallel(workflow_storage):
    """Test async parallel execution."""
    workflow = Workflow(
        name="Async Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = await workflow.arun(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2

@pytest.mark.asyncio
async def test_async_parallel_streaming(workflow_storage):
    """Test async parallel execution with streaming."""
    workflow = Workflow(
        name="Async Streaming Parallel",
        storage=workflow_storage,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

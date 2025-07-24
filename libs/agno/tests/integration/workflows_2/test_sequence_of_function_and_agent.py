"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator, Iterator

import pytest

from agno.run.v2.workflow import StepOutputEvent, WorkflowCompletedEvent, WorkflowRunResponse
from agno.workflow.v2 import StepInput, StepOutput, Workflow


def test_basic_sequence(workflow_storage):
    """Test basic sequence with just functions."""

    def step1(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"First: {step_input.message}")

    def step2(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Second: {step_input.previous_step_content}")

    workflow = Workflow(name="Basic Sequence", storage=workflow_storage, steps=[step1, step2])

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2
    assert "Second: First: test" in response.content


def test_function_and_agent_sequence(workflow_storage, test_agent):
    """Test sequence with function and agent."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.message}")

    workflow = Workflow(name="Agent Sequence", storage=workflow_storage, steps=[step, test_agent])

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2
    assert response.step_responses[1].success


def test_function_and_team_sequence(workflow_storage, test_team):
    """Test sequence with function and team."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.message}")

    workflow = Workflow(name="Team Sequence", storage=workflow_storage, steps=[step, test_team])

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 2
    assert response.step_responses[1].success


def test_function_streaming_sequence(workflow_storage):
    """Test streaming sequence."""

    def streaming_step(step_input: StepInput) -> Iterator[StepOutput]:
        yield StepOutput(content="Start")

    workflow = Workflow(name="Streaming", storage=workflow_storage, steps=[streaming_step])

    events = list(workflow.run(message="test", stream=True))
    step_events = [e for e in events if isinstance(e, StepOutputEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(completed_events) == 1
    assert any("Start" in str(e.content) for e in step_events)


@pytest.mark.asyncio
async def test_async_function_sequence(workflow_storage):
    """Test async sequence."""

    async def async_step(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content=f"Async: {step_input.message}")

    workflow = Workflow(name="Async", storage=workflow_storage, steps=[async_step])

    response = await workflow.arun(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert "Async: test" in response.content


@pytest.mark.asyncio
async def test_async_function_streaming(workflow_storage):
    """Test async streaming sequence."""

    async def async_streaming_step(step_input: StepInput) -> AsyncIterator[StepOutput]:
        yield StepOutput(content="Start")

    workflow = Workflow(name="Async Streaming", storage=workflow_storage, steps=[async_streaming_step])

    events = []
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)

    step_events = [e for e in events if isinstance(e, StepOutputEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(completed_events) == 1
    assert any("Start" in str(e.content) for e in step_events)


def test_mixed_sequence(workflow_storage, test_agent, test_team):
    """Test sequence with function, agent, and team."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.message}")

    workflow = Workflow(name="Mixed", storage=workflow_storage, steps=[step, test_agent, test_team])

    response = workflow.run(message="test")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 3
    assert "Function: test" in response.step_responses[0].content
    assert all(step.success for step in response.step_responses[1:])

"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator, Iterator

import pytest

from agno.run.workflow import StepOutputEvent, WorkflowCompletedEvent, WorkflowRunOutput
from agno.workflow import StepInput, StepOutput, Workflow


def test_basic_sequence(shared_db):
    """Test basic sequence with just functions."""

    def step1(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"First: {step_input.input}")

    def step2(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Second: {step_input.previous_step_content}")

    workflow = Workflow(name="Basic Sequence", db=shared_db, steps=[step1, step2])

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2
    assert "Second: First: test" in response.content


def test_function_and_agent_sequence(shared_db, test_agent):
    """Test sequence with function and agent."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.input}")

    workflow = Workflow(name="Agent Sequence", db=shared_db, steps=[step, test_agent])

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2
    assert response.step_results[1].success


def test_function_and_team_sequence(shared_db, test_team):
    """Test sequence with function and team."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.input}")

    workflow = Workflow(name="Team Sequence", db=shared_db, steps=[step, test_team])

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2
    assert response.step_results[1].success


def test_function_streaming_sequence(shared_db):
    """Test streaming sequence."""

    def streaming_step(step_input: StepInput) -> Iterator[StepOutput]:
        yield StepOutput(content="Start")

    workflow = Workflow(name="Streaming", db=shared_db, steps=[streaming_step])

    events = list(workflow.run(input="test", stream=True))
    step_events = [e for e in events if isinstance(e, StepOutputEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(completed_events) == 1
    assert any("Start" in str(e.content) for e in step_events)


@pytest.mark.asyncio
async def test_async_function_sequence(shared_db):
    """Test async sequence."""

    async def async_step(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content=f"Async: {step_input.input}")

    workflow = Workflow(name="Async", db=shared_db, steps=[async_step])

    response = await workflow.arun(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert "Async: test" in response.content


@pytest.mark.asyncio
async def test_async_function_streaming(shared_db):
    """Test async streaming sequence."""

    async def async_streaming_step(step_input: StepInput) -> AsyncIterator[StepOutput]:
        yield StepOutput(content="Start")

    workflow = Workflow(name="Async Streaming", db=shared_db, steps=[async_streaming_step])

    events = []
    async for event in workflow.arun(input="test", stream=True):
        events.append(event)

    step_events = [e for e in events if isinstance(e, StepOutputEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(completed_events) == 1
    assert any("Start" in str(e.content) for e in step_events)


def test_mixed_sequence(shared_db, test_agent, test_team):
    """Test sequence with function, agent, and team."""

    def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Function: {step_input.input}")

    workflow = Workflow(name="Mixed", db=shared_db, steps=[step, test_agent, test_team])

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 3
    assert "Function: test" in response.step_results[0].content
    assert all(step.success for step in response.step_results[1:])

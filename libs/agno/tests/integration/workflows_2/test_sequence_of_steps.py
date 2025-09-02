"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator

import pytest

from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.workflow.v2 import Step, StepInput, StepOutput, Workflow


def research_step_function(step_input: StepInput) -> StepOutput:
    """Minimal research function."""
    topic = step_input.message
    return StepOutput(content=f"Research: {topic}")


def content_step_function(step_input: StepInput) -> StepOutput:
    """Minimal content function."""
    prev = step_input.previous_step_content
    return StepOutput(content=f"Content: Hello World | Referencing: {prev}")


def test_function_sequence_non_streaming(workflow_storage):
    """Test basic function sequence."""
    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(message="test")

    assert isinstance(response, WorkflowRunResponse)
    assert "Content: Hello World | Referencing: Research: test" in response.content
    assert len(response.step_responses) == 2


def test_function_sequence_streaming(workflow_storage):
    """Test function sequence with streaming."""
    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    events = list(workflow.run(message="test", stream=True))

    assert len(events) > 0
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Content: Hello World | Referencing: Research: test" == completed_events[0].content


def test_agent_sequence_non_streaming(workflow_storage, test_agent):
    """Test agent sequence."""
    test_agent.instructions = "Do research on the topic and return the results."
    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", agent=test_agent),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(message="AI Agents")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert len(response.step_responses) == 2


def test_team_sequence_non_streaming(workflow_storage, test_team):
    """Test team sequence."""
    test_team.members[0].role = "Do research on the topic and return the results."
    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", team=test_team),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(message="test")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert len(response.step_responses) == 2


@pytest.mark.asyncio
async def test_async_function_sequence(workflow_storage):
    """Test async function sequence."""

    async def async_research(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)  # Minimal delay
        return StepOutput(content=f"Async: {step_input.message}")

    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", executor=async_research),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = await workflow.arun(message="test")

    assert isinstance(response, WorkflowRunResponse)
    assert "Async: test" in response.content
    assert "Content: Hello World | Referencing: Async: test" in response.content


@pytest.mark.asyncio
async def test_async_streaming(workflow_storage):
    """Test async streaming."""

    async def async_streaming_step(step_input: StepInput) -> AsyncIterator[str]:
        yield f"Stream: {step_input.message}"
        await asyncio.sleep(0.001)

    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="research", executor=async_streaming_step),
            Step(name="content", executor=content_step_function),
        ],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)

    assert len(events) > 0
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_step_chaining(workflow_storage):
    """Test that steps properly chain outputs."""

    def step1(step_input: StepInput) -> StepOutput:
        return StepOutput(content="step1_output")

    def step2(step_input: StepInput) -> StepOutput:
        prev = step_input.previous_step_content
        return StepOutput(content=f"step2_received_{prev}")

    workflow = Workflow(
        name="Test Workflow",
        storage=workflow_storage,
        steps=[
            Step(name="step1", executor=step1),
            Step(name="step2", executor=step2),
        ],
    )

    response = workflow.run(message="test")

    assert "step2_received_step1_output" in response.content

"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator

import pytest

from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.workflow import Step, StepInput, StepOutput, Workflow


def research_step_function(step_input: StepInput) -> StepOutput:
    """Minimal research function."""
    topic = step_input.input
    return StepOutput(content=f"Research: {topic}")


def content_step_function(step_input: StepInput) -> StepOutput:
    """Minimal content function."""
    prev = step_input.previous_step_content
    return StepOutput(content=f"Content: Hello World | Referencing: {prev}")


def test_function_sequence_non_streaming(shared_db):
    """Test basic function sequence."""
    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    assert "Content: Hello World | Referencing: Research: test" in response.content
    assert len(response.step_results) == 2


def test_function_sequence_streaming(shared_db):
    """Test function sequence with streaming."""
    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    events = list(workflow.run(input="test", stream=True))

    assert len(events) > 0
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Content: Hello World | Referencing: Research: test" == completed_events[0].content


def test_agent_sequence_non_streaming(shared_db, test_agent):
    """Test agent sequence."""
    test_agent.instructions = "Do research on the topic and return the results."
    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", agent=test_agent),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(input="AI Agents")

    assert isinstance(response, WorkflowRunOutput)
    assert response.content is not None
    assert len(response.step_results) == 2


def test_team_sequence_non_streaming(shared_db, test_team):
    """Test team sequence."""
    test_team.members[0].role = "Do research on the topic and return the results."
    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", team=test_team),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    assert response.content is not None
    assert len(response.step_results) == 2


@pytest.mark.asyncio
async def test_async_function_sequence(shared_db):
    """Test async function sequence."""

    async def async_research(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)  # Minimal delay
        return StepOutput(content=f"Async: {step_input.input}")

    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=async_research),
            Step(name="content", executor=content_step_function),
        ],
    )

    response = await workflow.arun(input="test")

    assert isinstance(response, WorkflowRunOutput)
    assert "Async: test" in response.content
    assert "Content: Hello World | Referencing: Async: test" in response.content


@pytest.mark.asyncio
async def test_async_streaming(shared_db):
    """Test async streaming."""

    async def async_streaming_step(step_input: StepInput) -> AsyncIterator[str]:
        yield f"Stream: {step_input.input}"
        await asyncio.sleep(0.001)

    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=async_streaming_step),
            Step(name="content", executor=content_step_function),
        ],
    )

    events = []
    async for event in await workflow.arun(input="test", stream=True):
        events.append(event)

    assert len(events) > 0
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1


def test_step_chaining(shared_db):
    """Test that steps properly chain outputs."""

    def step1(step_input: StepInput) -> StepOutput:
        return StepOutput(content="step1_output")

    def step2(step_input: StepInput) -> StepOutput:
        prev = step_input.previous_step_content
        return StepOutput(content=f"step2_received_{prev}")

    workflow = Workflow(
        name="Test Workflow",
        db=shared_db,
        steps=[
            Step(name="step1", executor=step1),
            Step(name="step2", executor=step2),
        ],
    )

    response = workflow.run(input="test")

    assert "step2_received_step1_output" in response.content

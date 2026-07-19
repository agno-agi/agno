"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator

import pytest

from agno.models.metrics import SessionMetrics
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
    async for event in workflow.arun(input="test", stream=True):
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


# Session Metrics Tests
def test_workflow_session_metrics_basic(shared_db):
    """Test that session metrics are calculated and stored for basic workflow."""
    workflow = Workflow(
        name="Session Metrics Test",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step_function),
            Step(name="content", executor=content_step_function),
        ],
    )

    # Run workflow multiple times to accumulate metrics
    response1 = workflow.run(input="test1")
    response2 = workflow.run(input="test2")

    # Check that responses are valid
    assert isinstance(response1, WorkflowRunOutput)
    assert isinstance(response2, WorkflowRunOutput)

    # Get session metrics
    session_metrics = workflow.get_session_metrics()

    # Basic assertions
    assert session_metrics is not None
    assert isinstance(session_metrics, SessionMetrics)


def test_workflow_session_metrics_aggregation(shared_db, test_agent):
    """Test that session metrics properly aggregate across multiple runs."""
    test_agent.instructions = "Respond with a short message about the topic."

    workflow = Workflow(
        name="Aggregation Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    # Run workflow multiple times
    responses = []
    for i in range(3):
        response = workflow.run(input=f"test topic {i}")
        responses.append(response)
        assert isinstance(response, WorkflowRunOutput)

    # Get session metrics
    session_metrics = workflow.get_session_metrics()

    assert session_metrics is not None

    # Check that tokens and costs are accumulated
    assert session_metrics.total_tokens > 0
    assert session_metrics.input_tokens > 0
    assert session_metrics.output_tokens > 0


@pytest.mark.asyncio
async def test_async_workflow_session_metrics(shared_db, test_agent):
    """Test that session metrics work with async workflows."""
    test_agent.instructions = "Respond with a short message about the topic."

    workflow = Workflow(
        name="Async Metrics Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    # Run workflow asynchronously
    response = await workflow.arun(input="async test")

    assert isinstance(response, WorkflowRunOutput)

    # Get session metrics
    session_metrics = workflow.get_session_metrics()

    assert session_metrics is not None
    assert session_metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_async_workflow_session_metrics_multiple_runs(shared_db):
    """Test session metrics accumulation across multiple async runs."""

    async def async_step(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)  # Minimal delay
        return StepOutput(content=f"Async response: {step_input.input}")

    workflow = Workflow(
        name="Multi Async Test",
        db=shared_db,
        steps=[
            Step(name="async_step", executor=async_step),
        ],
    )

    # Run multiple times
    for i in range(2):
        response = await workflow.arun(input=f"test {i}")
        assert isinstance(response, WorkflowRunOutput)

    # Get session metrics
    session_metrics = workflow.get_session_metrics()

    assert session_metrics is not None


def test_workflow_session_metrics_persistence(shared_db):
    """Test that session metrics persist across workflow instances."""
    session_id = "test_persistence_session"

    # Create first workflow instance
    workflow1 = Workflow(
        name="Persistence Test",
        db=shared_db,
        session_id=session_id,
        steps=[
            Step(name="step1", executor=research_step_function),
        ],
    )

    response1 = workflow1.run(input="test1")
    assert isinstance(response1, WorkflowRunOutput)

    # Create second workflow instance with same session_id
    workflow2 = Workflow(
        name="Persistence Test",
        db=shared_db,
        session_id=session_id,
        steps=[
            Step(name="step2", executor=content_step_function),
        ],
    )

    response2 = workflow2.run(input="test2")
    assert isinstance(response2, WorkflowRunOutput)

    # Both instances should see accumulated metrics
    metrics1 = workflow1.get_session_metrics()
    metrics2 = workflow2.get_session_metrics()

    assert metrics1 is not None
    assert metrics2 is not None


def test_workflow_session_metrics_different_sessions(shared_db):
    """Test that different sessions have separate metrics."""

    # Create two workflows with different session IDs
    workflow1 = Workflow(
        name="Session 1",
        db=shared_db,
        session_id="session_1",
        steps=[Step(name="step1", executor=research_step_function)],
    )

    workflow2 = Workflow(
        name="Session 2",
        db=shared_db,
        session_id="session_2",
        steps=[Step(name="step2", executor=content_step_function)],
    )

    # Run both workflows
    response1 = workflow1.run(input="test1")
    response2 = workflow2.run(input="test2")

    assert isinstance(response1, WorkflowRunOutput)
    assert isinstance(response2, WorkflowRunOutput)

    # Get metrics for each session
    metrics1 = workflow1.get_session_metrics()
    metrics2 = workflow2.get_session_metrics()

    # Each should have only 1 run
    assert metrics1 is not None
    assert metrics2 is not None


def test_workflow_session_metrics_error_handling(shared_db):
    """Test session metrics with workflow errors."""

    def failing_step(step_input: StepInput) -> StepOutput:
        raise Exception("Intentional test failure")

    workflow = Workflow(
        name="Error Test",
        db=shared_db,
        steps=[
            Step(name="success", executor=research_step_function),
            Step(name="failure", executor=failing_step),
        ],
    )

    # This should fail
    try:
        workflow.run(input="test")
    except Exception:
        pass  # Expected to fail

    # Run a successful one
    workflow_success = Workflow(
        name="Error Test",
        db=shared_db,
        session_id=workflow.session_id,  # Same session
        steps=[
            Step(name="success_only", executor=research_step_function),
        ],
    )

    response = workflow_success.run(input="test success")
    assert isinstance(response, WorkflowRunOutput)

    # Check metrics include both failed and successful runs
    session_metrics = workflow_success.get_session_metrics()
    assert session_metrics is not None


def test_workflow_session_metrics_aggregation_across_runs(shared_db, test_agent):
    """Test that metrics accumulate across multiple runs."""
    test_agent.instructions = "Respond with exactly 10 words about the topic."

    workflow = Workflow(
        name="Aggregation Test",
        db=shared_db,
        steps=[Step(name="agent_step", agent=test_agent)],
    )

    # Run once and get initial metrics
    workflow.run(input="first test")
    metrics_after_first = workflow.get_session_metrics()
    first_total_tokens = metrics_after_first.total_tokens if metrics_after_first else 0

    # Run again and verify metrics increased
    workflow.run(input="second test")
    metrics_after_second = workflow.get_session_metrics()

    assert metrics_after_second is not None
    assert metrics_after_second.total_tokens > first_total_tokens

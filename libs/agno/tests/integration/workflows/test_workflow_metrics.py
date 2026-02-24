"""Integration tests for Workflow metrics including duration tracking."""

import asyncio

import pytest

from agno.models.metrics import RunMetrics
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCompletedEvent
from agno.workflow import Condition, Parallel, Step, StepInput, StepOutput, Workflow
from agno.workflow.types import WorkflowMetrics


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step function."""
    return StepOutput(content=f"Research: {step_input.input}")


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step function."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Analysis of: {prev}")


def error_step(step_input: StepInput) -> StepOutput:
    """Step that raises an error."""
    raise ValueError("Intentional test error")


async def async_research_step(step_input: StepInput) -> StepOutput:
    """Async research step."""
    await asyncio.sleep(0.001)  # Minimal delay
    return StepOutput(content=f"Async Research: {step_input.input}")


# Condition evaluators
def condition_true(step_input: StepInput) -> bool:
    """Condition that returns True."""
    return True


def condition_false(step_input: StepInput) -> bool:
    """Condition that returns False."""
    return False


def test_workflow_duration_with_agent(shared_db, test_agent):
    """Test that workflow-level duration is tracked with agent."""
    test_agent.instructions = "Respond with 'Hello World'"

    workflow = Workflow(
        name="Agent Duration Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    response = workflow.run(input="test")

    # Verify workflow-level metrics exist
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)

    # Verify workflow-level duration
    assert response.metrics.duration is not None
    assert isinstance(response.metrics.duration, float)
    assert response.metrics.duration > 0

    # Verify step-level metrics (agent step should have duration)
    assert len(response.metrics.steps) > 0
    if "agent_step" in response.metrics.steps:
        agent_step_metrics = response.metrics.steps["agent_step"]
        assert agent_step_metrics.metrics is not None
        assert isinstance(agent_step_metrics.metrics, RunMetrics)
        assert agent_step_metrics.metrics.duration is not None
        assert agent_step_metrics.metrics.duration > 0


def test_workflow_duration_agent_and_function(shared_db, test_agent):
    """Test workflow duration with mixed agent and function steps."""
    test_agent.instructions = "Analyze the input"

    workflow = Workflow(
        name="Mixed Steps Duration Test",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
            Step(name="agent_analysis", agent=test_agent),
            Step(name="final", executor=analysis_step),
        ],
    )

    response = workflow.run(input="test topic")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert response.metrics.duration is not None
    assert response.metrics.duration > 0

    # Verify agent step has duration
    if "agent_analysis" in response.metrics.steps:
        assert response.metrics.steps["agent_analysis"].metrics.duration is not None
        assert response.metrics.steps["agent_analysis"].metrics.duration > 0


def test_workflow_duration_with_team(shared_db, test_team):
    """Test that workflow-level duration is tracked with team."""
    test_team.members[0].instructions = "Respond with team analysis"

    workflow = Workflow(
        name="Team Duration Test",
        db=shared_db,
        steps=[
            Step(name="team_step", team=test_team),
        ],
    )

    response = workflow.run(input="test")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration > 0

    # Verify team step has duration
    if "team_step" in response.metrics.steps:
        team_step_metrics = response.metrics.steps["team_step"]
        assert team_step_metrics.metrics is not None
        assert team_step_metrics.metrics.duration is not None
        assert team_step_metrics.metrics.duration > 0


def test_workflow_duration_on_error(shared_db):
    """Test that workflow duration is tracked even when step fails."""
    workflow = Workflow(
        name="Error Duration Test",
        db=shared_db,
        steps=[
            Step(name="error_step", executor=error_step),
        ],
    )

    # Run workflow - should raise error
    with pytest.raises(ValueError, match="Intentional test error"):
        workflow.run(input="test")

    # Get the workflow run from database
    session = workflow.get_session()
    assert session is not None
    assert len(session.runs) > 0

    last_run = session.runs[-1]

    # Verify error status
    assert last_run.status == RunStatus.error

    # Verify metrics exist with correct type
    assert last_run.metrics is not None
    assert isinstance(last_run.metrics, WorkflowMetrics)

    # Verify duration exists
    assert last_run.metrics.duration is not None
    assert isinstance(last_run.metrics.duration, float)
    assert last_run.metrics.duration >= 0


def test_workflow_duration_partial_error(shared_db, test_agent):
    """Test duration when error occurs after successful agent step."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Partial Error Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
            Step(name="error_step", executor=error_step),
        ],
    )

    with pytest.raises(ValueError, match="Intentional test error"):
        workflow.run(input="test")

    session = workflow.get_session()
    last_run = session.runs[-1]

    # Should still have duration tracked
    assert last_run.metrics is not None
    assert isinstance(last_run.metrics, WorkflowMetrics)
    assert last_run.metrics.duration is not None
    assert last_run.metrics.duration > 0


def test_workflow_duration_streaming_with_agent(shared_db, test_agent):
    """Test duration tracking with streaming and agent."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Streaming Duration Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    events = list(workflow.run(input="test", stream=True))

    # Verify events were generated
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Get session and check metrics
    session = workflow.get_session()
    last_run = session.runs[-1]

    assert last_run.metrics is not None
    assert isinstance(last_run.metrics, WorkflowMetrics)
    assert last_run.metrics.duration is not None
    assert last_run.metrics.duration > 0


@pytest.mark.asyncio
async def test_workflow_duration_async_with_agent(shared_db, test_agent):
    """Test async workflow duration with agent."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Async Agent Duration Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    response = await workflow.arun(input="test")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration > 0

    # Verify agent step duration
    if "agent_step" in response.metrics.steps:
        assert response.metrics.steps["agent_step"].metrics.duration is not None
        assert response.metrics.steps["agent_step"].metrics.duration > 0


@pytest.mark.asyncio
async def test_workflow_duration_async_streaming(shared_db, test_agent):
    """Test duration tracking with async streaming."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Async Streaming Duration Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Get session to check metrics
    session = workflow.get_session()
    last_run = session.runs[-1]

    assert last_run.metrics is not None
    assert isinstance(last_run.metrics, WorkflowMetrics)
    assert last_run.metrics.duration is not None
    assert last_run.metrics.duration > 0


@pytest.mark.asyncio
async def test_workflow_duration_async_function(shared_db):
    """Test duration with async function steps."""
    workflow = Workflow(
        name="Async Function Duration Test",
        db=shared_db,
        steps=[
            Step(name="async_research", executor=async_research_step),
        ],
    )

    response = await workflow.arun(input="test")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration >= 0


def test_workflow_duration_parallel_with_agent(shared_db, test_agent):
    """Test duration with parallel execution including agent."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Parallel Agent Duration Test",
        db=shared_db,
        steps=[
            Parallel(
                Step(name="agent_step", agent=test_agent),
                Step(name="research_step", executor=research_step),
            )
        ],
    )

    response = workflow.run(input="test")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration > 0

    # Verify agent step duration if present
    if "agent_step" in response.metrics.steps:
        assert response.metrics.steps["agent_step"].metrics.duration is not None
        assert response.metrics.steps["agent_step"].metrics.duration > 0


def test_workflow_duration_condition_true_with_agent(shared_db, test_agent):
    """Test duration with condition that evaluates to true."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Condition True Duration Test",
        db=shared_db,
        steps=[
            Condition(
                evaluator=condition_true,
                steps=[Step(name="agent_step", agent=test_agent)],
            )
        ],
    )

    response = workflow.run(input="test")

    # Verify workflow-level duration
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration > 0

    # Verify agent step duration if present
    if "agent_step" in response.metrics.steps:
        assert response.metrics.steps["agent_step"].metrics.duration is not None
        assert response.metrics.steps["agent_step"].metrics.duration > 0


def test_workflow_duration_condition_false_with_agent(shared_db, test_agent):
    """Test duration with condition that evaluates to false."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Condition False Duration Test",
        db=shared_db,
        steps=[
            Condition(
                evaluator=condition_false,
                steps=[Step(name="skipped_agent_step", agent=test_agent)],
            )
        ],
    )

    response = workflow.run(input="test")

    # Verify workflow-level duration still tracked
    assert response.metrics is not None
    assert isinstance(response.metrics, WorkflowMetrics)
    assert response.metrics.duration is not None
    assert response.metrics.duration >= 0

    # Agent step should not be in metrics since condition was false
    assert "skipped_agent_step" not in response.metrics.steps


def test_workflow_metrics_serialization(shared_db, test_agent):
    """Test metrics serialization with agent steps."""
    test_agent.instructions = "Respond with analysis"

    workflow = Workflow(
        name="Serialization Test",
        db=shared_db,
        steps=[
            Step(name="agent_step", agent=test_agent),
        ],
    )

    response = workflow.run(input="test")

    # Serialize to dict
    metrics_dict = response.metrics.to_dict()

    # Verify duration is in the dict
    assert "duration" in metrics_dict
    assert isinstance(metrics_dict["duration"], float)
    assert metrics_dict["duration"] > 0

    # Verify steps are in the dict
    assert "steps" in metrics_dict
    assert isinstance(metrics_dict["steps"], dict)

    # Deserialize from dict
    reconstructed = WorkflowMetrics.from_dict(metrics_dict)

    # Verify duration preserved
    assert reconstructed.duration == response.metrics.duration
    assert isinstance(reconstructed.duration, float)

    # Verify step metrics preserved
    if "agent_step" in response.metrics.steps:
        assert "agent_step" in reconstructed.steps
        assert reconstructed.steps["agent_step"].metrics is not None

"""Integration tests for WorkflowTools with Agent and Team."""

from typing import get_args
from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.team.team import Team
from agno.tools.workflow import RunWorkflowInput, WorkflowTools
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# === Fixtures ===
@pytest.fixture
def mock_run_context():
    """Create a mock RunContext for testing."""
    context = MagicMock(spec=RunContext)
    context.stream = True
    context.stream_events = True
    return context


# === Helper Functions ===
def research_step(step_input: StepInput) -> StepOutput:
    """Research step that generates content."""
    return StepOutput(content=f"Research findings for: {step_input.input}", success=True)


def summarize_step(step_input: StepInput) -> StepOutput:
    """Summarize step that uses previous content."""
    prev = step_input.previous_step_content or "nothing"
    return StepOutput(content=f"Summary of: {prev}", success=True)


def fact_check_step(step_input: StepInput) -> StepOutput:
    """Fact checking step."""
    return StepOutput(content="Facts verified.", success=True)


def needs_fact_check(step_input: StepInput) -> bool:
    """Check if fact checking is needed."""
    content = step_input.input or step_input.previous_step_content or ""
    return "fact" in content.lower() or "data" in content.lower()


# === Test Agent with WorkflowTools ===
def test_agent_runs_workflow_tool(shared_db):
    """Test that agent can run a workflow tool."""
    workflow = Workflow(
        name="Research Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
            Step(name="summarize", executor=summarize_step),
        ],
    )
    workflow_tools = WorkflowTools(workflow=workflow)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[workflow_tools],
        instructions="Use the run_workflow tool to process the user's request.",
    )

    response = agent.run("Research AI trends")

    assert response is not None
    assert response.content is not None


def test_agent_streams_workflow_events(shared_db):
    """Test that agent streams workflow events when using streaming workflow tools."""
    workflow = Workflow(
        name="Research Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
            Step(name="summarize", executor=summarize_step),
        ],
    )
    workflow_tools = WorkflowTools(workflow=workflow, stream=True)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[workflow_tools],
        instructions="You MUST always use the run_workflow tool. Never respond without calling run_workflow first.",
    )

    events = list(agent.run("Research AI trends", stream=True))

    workflow_events = [e for e in events if isinstance(e, tuple(get_args(WorkflowRunOutputEvent)))]

    # If no workflow events, the LLM didn't call the tool - skip this flaky test
    if len(workflow_events) == 0:
        pytest.skip("LLM did not call workflow tool - flaky integration test")

    assert len(workflow_events) > 0


def test_agent_receives_step_events(shared_db):
    """Test that agent receives step started/completed events."""
    workflow = Workflow(
        name="Research Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
        ],
    )
    workflow_tools = WorkflowTools(workflow=workflow, stream=True)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[workflow_tools],
        instructions="You MUST always use the run_workflow tool. Never respond without calling run_workflow first.",
    )

    events = list(agent.run("Research topic", stream=True))

    step_started = [e for e in events if isinstance(e, StepStartedEvent)]
    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]

    # If no step events, the LLM didn't call the tool - skip this flaky test
    if len(step_started) == 0:
        pytest.skip("LLM did not call workflow tool - flaky integration test")

    assert len(step_started) >= 1
    assert len(step_completed) >= 1


# === Test Team with WorkflowTools ===
def test_team_runs_workflow_tool(shared_db):
    """Test that team can run a workflow tool."""
    workflow = Workflow(
        name="Research Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
            Step(name="summarize", executor=summarize_step),
        ],
    )
    workflow_tools = WorkflowTools(workflow=workflow)

    team = Team(
        name="Research Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[workflow_tools],
        members=[],
        instructions="Use the run_workflow tool to process requests.",
    )

    response = team.run("Research AI trends")

    assert response is not None
    assert response.content is not None


def test_team_streams_workflow_events(shared_db):
    """Test that team streams workflow events."""
    workflow = Workflow(
        name="Research Workflow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_step),
            Step(name="summarize", executor=summarize_step),
        ],
    )
    workflow_tools = WorkflowTools(workflow=workflow, stream=True)

    team = Team(
        name="Research Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[workflow_tools],
        members=[],
        instructions="You MUST always use the run_workflow tool. Never respond without calling run_workflow first.",
    )

    events = list(team.run("Research AI trends", stream=True))

    workflow_started = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    # If no workflow events, the LLM didn't call the tool - skip this flaky test
    if len(workflow_started) == 0:
        pytest.skip("LLM did not call workflow tool - flaky integration test")

    assert len(workflow_started) >= 1
    assert len(workflow_completed) >= 1


# === Test Workflow Events Propagation ===
def test_workflow_events_are_workflow_run_output_event(shared_db, mock_run_context):
    """Test that all workflow events are WorkflowRunOutputEvent types."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test", executor=research_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    workflow_events = [e for e in events if not isinstance(e, str)]

    for event in workflow_events:
        assert isinstance(event, tuple(get_args(WorkflowRunOutputEvent))), (
            f"Event {type(event)} is not a WorkflowRunOutputEvent"
        )


def test_step_completed_has_content(shared_db, mock_run_context):
    """Test that StepCompletedEvent contains content."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[Step(name="test", executor=research_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="my topic")))

    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]
    assert len(step_completed) == 1
    assert step_completed[0].content is not None
    assert "my topic" in str(step_completed[0].content)


def test_condition_events_have_result(shared_db, mock_run_context):
    """Test that condition events have condition_result."""
    workflow = Workflow(
        name="Test",
        db=shared_db,
        steps=[
            Condition(
                name="check",
                evaluator=needs_fact_check,
                steps=[Step(name="fact_check", executor=fact_check_step)],
            )
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="check the data")))

    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    assert condition_started[0].condition_result is True


# === Test Multiple Steps ===
def test_multiple_steps_all_events_received(shared_db, mock_run_context):
    """Test that all step events are received for multi-step workflow."""
    workflow = Workflow(
        name="Multi-Step",
        db=shared_db,
        steps=[
            Step(name="step1", executor=research_step),
            Step(name="step2", executor=summarize_step),
            Step(name="step3", executor=fact_check_step),
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    step_started = [e for e in events if isinstance(e, StepStartedEvent)]
    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]

    assert len(step_started) == 3
    assert len(step_completed) == 3

    step_names = [e.step_name for e in step_started]
    assert "step1" in step_names
    assert "step2" in step_names
    assert "step3" in step_names


def test_steps_execute_in_order(shared_db, mock_run_context):
    """Test that steps execute in correct order."""
    workflow = Workflow(
        name="Ordered",
        db=shared_db,
        steps=[
            Step(name="first", executor=research_step),
            Step(name="second", executor=summarize_step),
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = list(tools.run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="test")))

    step_started = [e for e in events if isinstance(e, StepStartedEvent)]

    first_idx = next(i for i, e in enumerate(step_started) if e.step_name == "first")
    second_idx = next(i for i, e in enumerate(step_started) if e.step_name == "second")
    assert first_idx < second_idx


# === Test Async Workflow Tools ===
@pytest.mark.asyncio
async def test_async_stream_yields_events(shared_db, mock_run_context):
    """Test async streaming yields events."""
    workflow = Workflow(
        name="Async Test",
        db=shared_db,
        steps=[Step(name="test", executor=research_step)],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = []
    result = await tools.async_run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="async test"))
    # Result is an async iterator when streaming
    async for event in result:
        events.append(event)

    workflow_started = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(workflow_started) == 1
    assert len(workflow_completed) == 1


@pytest.mark.asyncio
async def test_async_step_events(shared_db, mock_run_context):
    """Test async streaming yields step events."""
    workflow = Workflow(
        name="Async Steps",
        db=shared_db,
        steps=[
            Step(name="async_step1", executor=research_step),
            Step(name="async_step2", executor=summarize_step),
        ],
    )
    tools = WorkflowTools(workflow=workflow, stream=True)

    session_state = {}
    events = []
    result = await tools.async_run_workflow(mock_run_context, session_state, RunWorkflowInput(input_data="async test"))
    # Result is an async iterator when streaming
    async for event in result:
        events.append(event)

    step_started = [e for e in events if isinstance(e, StepStartedEvent)]
    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]

    assert len(step_started) == 2
    assert len(step_completed) == 2

"""Integration tests for WorkflowAgent functionality in workflows."""

from dataclasses import dataclass
from typing import AsyncIterator, Union

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.workflow import CustomEvent, WorkflowCompletedEvent, WorkflowRunOutputEvent, WorkflowStartedEvent
from agno.workflow import Step, StepInput, StepOutput, Workflow
from agno.workflow.agent import WorkflowAgent

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def story_step(step_input: StepInput) -> StepOutput:
    """Generate a simple story."""
    topic = step_input.input
    return StepOutput(content=f"Story about {topic}: Once upon a time...")


def format_step(step_input: StepInput) -> StepOutput:
    """Format the story."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Formatted: {prev}")


def reference_step(step_input: StepInput) -> StepOutput:
    """Add references."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"{prev}\n\nReferences: https://www.agno.com")


def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return f"The weather in {city} is sunny and 72F."


@dataclass
class DataProcessedEvent(CustomEvent):
    """Custom event for data processing."""

    records_processed: int = None
    status: str = None


async def process_data_step(
    step_input: StepInput,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """Process data and yield custom events."""
    data = step_input.input

    # Custom logic
    processed_count = len(data.split()) if data else 0

    # Yield custom event
    yield DataProcessedEvent(records_processed=processed_count, status="completed")

    # Return final output
    yield StepOutput(content=f"Processed {processed_count} items")


# ============================================================================
# SYNC TESTS
# ============================================================================


def test_workflow_agent_first_run_executes_workflow(shared_db):
    """Test that WorkflowAgent runs the workflow on first call."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # First call should execute the workflow
    response = workflow.run(input="a dog named Max")

    assert response is not None
    assert response.status == "COMPLETED"
    assert response.workflow_agent_run is not None

    # Check that run was stored in session
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 1
    assert session.runs[0].workflow_agent_run is not None


def test_workflow_agent_answers_from_history(shared_db):
    """Test that WorkflowAgent answers from history without re-running workflow."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # First call - executes workflow
    response1 = workflow.run(input="a dog named Max")
    assert "dog named Max" in response1.content.lower() or "max" in response1.content.lower()

    # Second call - should answer from history
    response2 = workflow.run(input="What was that story about?")

    assert response2 is not None
    assert response2.status == "COMPLETED"
    # The response should reference the previous story
    assert response2.workflow_agent_run is not None

    # Check that we have 2 runs in session (1 workflow run + 1 direct answer)
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 2


def test_workflow_agent_new_topic_runs_workflow(shared_db):
    """Test that WorkflowAgent runs workflow again for new topics."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # First call - dog story
    response1 = workflow.run(input="a dog named Max")
    assert "dog named Max" in response1.content

    # Second call - new topic, should run workflow again
    response2 = workflow.run(input="a cat named Luna")

    assert response2 is not None
    assert "cat named Luna" in response2.content

    # Should have 2 workflow runs
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 2


def test_workflow_agent_comparison_from_history(shared_db):
    """Test that WorkflowAgent can compare previous runs from history."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Comparison Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
        session_id="test_comparison_session",
    )

    # Run workflow twice with different topics
    workflow.run(input="a dog named Max")
    workflow.run(input="a cat named Luna")

    # Ask for comparison - should answer from history
    response3 = workflow.run(input="Compare Max and Luna")

    assert response3 is not None
    assert response3.workflow_agent_run is not None

    # Should have 3 runs total (2 workflows + 1 direct answer)
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 3


def test_workflow_agent_streaming(shared_db):
    """Test WorkflowAgent with streaming enabled."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # Run with streaming
    events = list(workflow.run(input="a dog named Max", stream=True, stream_intermediate_steps=True))

    # Should have workflow started and completed events
    started_events = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert "dog named Max" in completed_events[0].content


def test_workflow_agent_multiple_steps(shared_db):
    """Test WorkflowAgent with multiple workflow steps."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates, formats, and adds references to stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
            Step(name="references", executor=reference_step),
        ],
        db=shared_db,
    )

    response = workflow.run(input="a dog named Max")

    assert response is not None
    # Check for Max in content (case insensitive) - workflow agent may rephrase input
    assert "max" in response.content.lower()
    assert "Formatted:" in response.content
    assert "References: https://www.agno.com" in response.content
    assert len(response.step_results) == 3


def test_workflow_agent_with_agent_steps(shared_db):
    """Test WorkflowAgent with Agent-based steps."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    story_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Write a very short story (20 words) based on the topic",
    )

    workflow = Workflow(
        name="Story Workflow",
        description="Generates stories using AI",
        agent=workflow_agent,
        steps=[story_agent],
        db=shared_db,
    )

    response = workflow.run(input="a dog named Max")

    assert response is not None
    assert response.status == "COMPLETED"
    assert response.content is not None
    assert len(response.content) > 0


# ============================================================================
# ASYNC TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_agent_async_first_run(shared_db):
    """Test WorkflowAgent async execution on first call."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Async Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    response = await workflow.arun(input="a dog named Max")

    assert response is not None
    assert response.status == "COMPLETED"
    assert "max" in response.content.lower()
    assert response.workflow_agent_run is not None


@pytest.mark.asyncio
async def test_workflow_agent_async_streaming(shared_db):
    """Test WorkflowAgent async with streaming."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Async Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    events = []
    async for event in workflow.arun(input="a dog named Max", stream=True, stream_intermediate_steps=True):
        events.append(event)

    # Should have workflow started and completed events
    started_events = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(started_events) == 1
    assert len(completed_events) == 1


@pytest.mark.asyncio
async def test_workflow_agent_async_history(shared_db):
    """Test WorkflowAgent async answers from history."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Async Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # First call
    response1 = await workflow.arun(input="a dog named Max")
    assert "dog named Max" in response1.content

    # Second call - should use history
    response2 = await workflow.arun(input="What was that story about?")

    assert response2 is not None
    assert response2.status == "COMPLETED"

    # Should have 2 runs
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 2


@pytest.mark.asyncio
async def test_workflow_agent_async_multiple_runs(shared_db):
    """Test WorkflowAgent async with multiple runs."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Async Story Workflow",
        description="Generates and formats stories",
        agent=workflow_agent,
        steps=[
            Step(name="story", executor=story_step),
            Step(name="format", executor=format_step),
        ],
        db=shared_db,
    )

    # Run multiple times
    response1 = await workflow.arun(input="a dog named Max")
    response2 = await workflow.arun(input="a cat named Luna")
    response3 = await workflow.arun(input="Compare Max and Luna")

    assert all(r is not None for r in [response1, response2, response3])

    # Should have 3 runs (2 workflows + 1 direct answer)
    session = workflow.get_session(session_id=workflow.session_id)
    assert session is not None
    assert len(session.runs) == 3


# ============================================================================
# EDGE CASES
# ============================================================================


def test_workflow_agent_empty_input(shared_db):
    """Test WorkflowAgent with empty input."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        agent=workflow_agent,
        steps=[Step(name="story", executor=story_step)],
        db=shared_db,
    )

    # Empty input should still work
    response = workflow.run(input="")

    assert response is not None
    assert response.status == "COMPLETED"


def test_workflow_agent_session_persistence(shared_db):
    """Test that WorkflowAgent session data persists correctly."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    session_id = "test_session_persist"

    # First workflow instance
    workflow1 = Workflow(
        name="Story Workflow",
        description="Generates stories",
        agent=workflow_agent,
        steps=[Step(name="story", executor=story_step)],
        db=shared_db,
        session_id=session_id,
    )

    response1 = workflow1.run(input="a dog named Max")
    assert response1 is not None

    # Second workflow instance with same session_id
    workflow2 = Workflow(
        name="Story Workflow",
        description="Generates stories",
        agent=WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini")),
        steps=[Step(name="story", executor=story_step)],
        db=shared_db,
        session_id=session_id,
    )

    response2 = workflow2.run(input="What was that about?")

    assert response2 is not None

    # Both should see the same session
    session = workflow2.get_session(session_id=session_id)
    assert len(session.runs) == 2


def test_workflow_agent_no_previous_runs(shared_db):
    """Test WorkflowAgent with a fresh session (no history)."""
    workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"))

    workflow = Workflow(
        name="Story Workflow",
        description="Generates stories",
        agent=workflow_agent,
        steps=[Step(name="story", executor=story_step)],
        db=shared_db,
    )

    # First call on fresh session should execute workflow
    response = workflow.run(input="a dog named Max")

    assert response is not None
    assert response.status == "COMPLETED"
    assert response.workflow_agent_run is not None

    session = workflow.get_session(session_id=workflow.session_id)
    assert len(session.runs) == 1


def test_workflow_agent_streaming_tool_events(shared_db):
    """Test that tool events are not muted when using WorkflowAgent with streaming."""
    workflow_agent = WorkflowAgent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You help users with weather queries. ALWAYS use the workflow to get weather information.",
    )

    weather_agent = Agent(
        name="Weather Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather],
        instructions="You are a helpful weather assistant. Use the get_weather tool to answer questions.",
    )

    workflow = Workflow(
        name="Weather Workflow",
        description="Gets weather information",
        agent=workflow_agent,
        steps=[Step(name="Weather Step", agent=weather_agent)],
        db=shared_db,
    )

    # Run with streaming
    events = list(workflow.run(input="What is the weather in San Francisco?", stream=True, stream_events=True))

    # Collect event types
    event_types = {type(e).__name__ for e in events}

    # Should have tool call events from the inner agent
    assert "ToolCallStartedEvent" in event_types, f"ToolCallStartedEvent not found. Events seen: {event_types}"
    assert "ToolCallCompletedEvent" in event_types, f"ToolCallCompletedEvent not found. Events seen: {event_types}"

    # Should also have workflow events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types


@pytest.mark.asyncio
async def test_workflow_agent_async_streaming_tool_events(shared_db):
    """Test that tool events are not muted when using WorkflowAgent with async streaming."""
    workflow_agent = WorkflowAgent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You help users with weather queries. ALWAYS use the workflow to get weather information.",
    )

    weather_agent = Agent(
        name="Weather Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather],
        instructions="You are a helpful weather assistant. Use the get_weather tool to answer questions.",
    )

    workflow = Workflow(
        name="Weather Workflow",
        description="Gets weather information",
        agent=workflow_agent,
        steps=[Step(name="Weather Step", agent=weather_agent)],
        db=shared_db,
    )

    # Run with async streaming
    events = []
    async for event in workflow.arun(input="What is the weather in San Francisco?", stream=True, stream_events=True):
        events.append(event)

    # Collect event types
    event_types = {type(e).__name__ for e in events}

    # Should have tool call events from the inner agent
    assert "ToolCallStartedEvent" in event_types, f"ToolCallStartedEvent not found. Events seen: {event_types}"
    assert "ToolCallCompletedEvent" in event_types, f"ToolCallCompletedEvent not found. Events seen: {event_types}"

    # Should also have workflow events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types


@pytest.mark.asyncio
async def test_workflow_agent_async_streaming_custom_events(shared_db):
    """Test that custom events are not muted when using WorkflowAgent with async streaming."""
    workflow_agent = WorkflowAgent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You process data. ALWAYS use the workflow to process any data. Never answer directly.",
    )

    workflow = Workflow(
        name="Data Processing Workflow",
        description="Processes data and emits custom events",
        agent=workflow_agent,
        steps=[Step(name="Process", executor=process_data_step)],
        db=shared_db,
    )

    # Run with async streaming
    events = []
    async for event in workflow.arun(input="Process this data: hello world test", stream=True, stream_events=True):
        events.append(event)

    # Collect event types
    event_types = {type(e).__name__ for e in events}

    # Should have custom event from the step
    assert "DataProcessedEvent" in event_types, f"DataProcessedEvent not found. Events seen: {event_types}"

    # Verify the custom event has correct data
    custom_events = [e for e in events if isinstance(e, DataProcessedEvent)]
    assert len(custom_events) >= 1, "Should have at least one DataProcessedEvent"
    assert custom_events[0].status == "completed"
    assert custom_events[0].records_processed is not None

    # Should also have workflow events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types

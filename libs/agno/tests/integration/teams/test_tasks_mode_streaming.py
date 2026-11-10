"""
Integration tests for TeamMode.tasks streaming functionality.

Tests verify that task mode emits proper events during streaming:
- TaskIterationStartedEvent
- TaskIterationCompletedEvent
- TaskStateUpdatedEvent
- Tool call events for task tools (create_task, execute_task, mark_all_complete)
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import (
    TaskIterationCompletedEvent,
    TaskIterationStartedEvent,
    TaskStateUpdatedEvent,
    TeamRunEvent,
)
from agno.team.mode import TeamMode
from agno.team.team import Team


@pytest.fixture
def researcher_agent():
    """Create a researcher agent for testing."""
    return Agent(
        name="Researcher",
        role="Researches topics and gathers information",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Research the given topic.", "Provide factual information."],
    )


@pytest.fixture
def summarizer_agent():
    """Create a summarizer agent for testing."""
    return Agent(
        name="Summarizer",
        role="Summarizes information into concise points",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Create clear, concise summaries.", "Highlight key points."],
    )


@pytest.fixture
def tasks_team(researcher_agent, summarizer_agent):
    """Create a team in tasks mode for testing."""
    return Team(
        name="Research Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[researcher_agent, summarizer_agent],
        instructions=[
            "You are a research team leader. Follow these steps exactly:",
            "1. Create a task for the Researcher to gather information.",
            "2. Execute the Researcher's task.",
            "3. Create a task for the Summarizer to summarize the research.",
            "4. Execute the Summarizer's task.",
            "5. Call mark_all_complete with a final summary when all tasks are done.",
        ],
        max_iterations=3,
        telemetry=False,
    )


def test_tasks_mode_emits_iteration_events(tasks_team):
    """Test that tasks mode emits TaskIterationStartedEvent and TaskIterationCompletedEvent."""
    started_events = []
    completed_events = []
    for event in tasks_team.run(
        "What are 3 benefits of exercise?",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskIterationStartedEvent):
            started_events.append(event)
        elif isinstance(event, TaskIterationCompletedEvent):
            completed_events.append(event)

    # Should have TaskIterationStartedEvent
    assert len(started_events) >= 1, "Should have at least one iteration started event"

    # Verify TaskIterationStartedEvent fields
    first_started = started_events[0]
    assert first_started.event == TeamRunEvent.task_iteration_started.value
    assert first_started.iteration >= 1
    assert first_started.max_iterations == 3

    # Should have TaskIterationCompletedEvent
    assert len(completed_events) >= 1, "Should have at least one iteration completed event"

    # Verify TaskIterationCompletedEvent fields
    first_completed = completed_events[0]
    assert first_completed.event == TeamRunEvent.task_iteration_completed.value
    assert first_completed.iteration >= 1
    assert first_completed.max_iterations == 3


def test_tasks_mode_emits_task_state_updated(tasks_team):
    """Test that tasks mode emits TaskStateUpdatedEvent when task state changes."""
    state_events = []
    for event in tasks_team.run(
        "List 2 programming languages and their main use cases.",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskStateUpdatedEvent):
            state_events.append(event)

    # Should have TaskStateUpdatedEvent
    assert len(state_events) >= 1, "Should have at least one task state updated event"

    # Verify TaskStateUpdatedEvent fields
    for state_event in state_events:
        assert state_event.event == TeamRunEvent.task_state_updated.value
        # task_summary should contain task information
        assert state_event.task_summary is not None or state_event.goal_complete is not None


def test_tasks_mode_emits_tool_call_events(tasks_team):
    """Test that tasks mode emits tool call events for task tools."""
    events = {}
    for event in tasks_team.run(
        "Name one country and its capital.",
        stream=True,
        stream_events=True,
    ):
        if hasattr(event, "event"):
            event_name = event.event
            if event_name not in events:
                events[event_name] = []
            events[event_name].append(event)

    # Should have tool_call_started events
    assert TeamRunEvent.tool_call_started.value in events, "Should emit tool_call_started events"
    tool_started_events = events[TeamRunEvent.tool_call_started.value]

    # Check that task-related tools are called
    tool_names = [e.tool.tool_name for e in tool_started_events if e.tool]
    task_tools = {"create_task", "execute_task", "mark_all_complete", "update_task_status"}

    # At least one task tool should be called
    assert any(name in task_tools for name in tool_names), f"Should call task tools, got: {tool_names}"


def test_tasks_mode_basic_streaming(tasks_team):
    """Test basic streaming functionality in tasks mode."""
    content_events = []
    for event in tasks_team.run(
        "What is 2+2?",
        stream=True,
        stream_events=True,
    ):
        if hasattr(event, "event") and event.event == TeamRunEvent.run_content.value:
            content_events.append(event)

    # Should have content events
    assert len(content_events) > 0, "Should emit run_content events"


@pytest.mark.asyncio
async def test_tasks_mode_async_streaming(tasks_team):
    """Test async streaming functionality in tasks mode."""
    started_events = []
    completed_events = []
    async for event in tasks_team.arun(
        "What color is the sky?",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskIterationStartedEvent):
            started_events.append(event)
        elif isinstance(event, TaskIterationCompletedEvent):
            completed_events.append(event)

    # Should have TaskIterationStartedEvent
    assert len(started_events) >= 1, "Async should emit TaskIterationStartedEvent"

    # Should have TaskIterationCompletedEvent
    assert len(completed_events) >= 1, "Async should emit TaskIterationCompletedEvent"


def test_tasks_mode_run_started_and_completed_events(tasks_team):
    """Test that tasks mode emits run_started and run_completed events."""
    events = {}
    for event in tasks_team.run(
        "Say hello",
        stream=True,
        stream_events=True,
    ):
        if hasattr(event, "event"):
            event_name = event.event
            if event_name not in events:
                events[event_name] = []
            events[event_name].append(event)

    # Should have run_started
    assert TeamRunEvent.run_started.value in events, "Should emit run_started"
    assert len(events[TeamRunEvent.run_started.value]) == 1

    # Should have run_completed
    assert TeamRunEvent.run_completed.value in events, "Should emit run_completed"
    assert len(events[TeamRunEvent.run_completed.value]) == 1


def test_tasks_mode_iteration_numbers_increment():
    """Test that iteration numbers increment correctly across multiple iterations."""
    team = Team(
        name="Simple Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[
            Agent(
                name="Helper",
                model=OpenAIChat(id="gpt-4o-mini"),
                instructions=["Help with the task."],
            )
        ],
        instructions=[
            "Create one task for Helper and execute it.",
            "Then call mark_all_complete.",
        ],
        max_iterations=5,
        telemetry=False,
    )

    iteration_started_events = []
    for event in team.run(
        "Say hi",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskIterationStartedEvent):
            iteration_started_events.append(event)

    # Should have at least one iteration
    assert len(iteration_started_events) >= 1

    # First iteration should be 1
    assert iteration_started_events[0].iteration == 1

    # If there are multiple iterations, they should increment
    for i, event in enumerate(iteration_started_events):
        assert event.iteration == i + 1, f"Iteration {i} should have iteration number {i + 1}"


def test_tasks_mode_max_iterations_in_events():
    """Test that max_iterations is correctly reported in events."""
    max_iter = 4
    team = Team(
        name="Test Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        instructions=["Answer directly."],
        max_iterations=max_iter,
        telemetry=False,
    )

    for event in team.run(
        "Hi",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskIterationStartedEvent):
            assert event.max_iterations == max_iter, f"max_iterations should be {max_iter}"
            break


def test_tasks_mode_goal_complete_in_state_event():
    """Test that goal_complete is set correctly in TaskStateUpdatedEvent."""
    team = Team(
        name="Goal Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[
            Agent(
                name="Worker",
                model=OpenAIChat(id="gpt-4o-mini"),
                instructions=["Complete the task."],
            )
        ],
        instructions=[
            "Create a task for Worker, execute it, then call mark_all_complete with summary.",
        ],
        max_iterations=3,
        telemetry=False,
    )

    state_events = []
    for event in team.run(
        "Say done",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, TaskStateUpdatedEvent):
            state_events.append(event)

    # Should have at least one state event
    assert len(state_events) >= 1, "Should have TaskStateUpdatedEvent"

    # Check if any state event has goal_complete (model may or may not call mark_all_complete)
    # The test verifies the event structure is correct
    for event in state_events:
        assert hasattr(event, "goal_complete"), "TaskStateUpdatedEvent should have goal_complete field"
        assert hasattr(event, "task_summary"), "TaskStateUpdatedEvent should have task_summary field"

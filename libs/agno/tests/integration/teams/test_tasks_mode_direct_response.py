"""Integration tests for tasks mode direct response behavior.

Verifies that tasks mode responds directly to simple messages (greetings,
simple questions) without creating tasks or calling mark_all_complete,
while still decomposing complex requests into tasks.
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import (
    TaskIterationCompletedEvent,
    TaskIterationStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.team.mode import TeamMode
from agno.team.team import Team


@pytest.fixture
def tasks_team():
    """Create a simple tasks-mode team for testing."""
    researcher = Agent(
        name="Researcher",
        role="Researches topics and gathers information",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Research the given topic.", "Provide factual information."],
    )
    summarizer = Agent(
        name="Summarizer",
        role="Summarizes information into concise points",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Create clear, concise summaries.", "Highlight key points."],
    )
    return Team(
        name="Test Research Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[researcher, summarizer],
        instructions=[
            "You are a research team leader.",
            "For research requests, create tasks for your members.",
            "For simple greetings or questions, respond directly.",
        ],
        max_iterations=3,
        telemetry=False,
    )


def test_tasks_mode_greeting_no_tool_calls(tasks_team):
    """A simple greeting should get a direct response without task tools being called."""
    response = tasks_team.run("hi")

    # Should have content (a greeting response)
    assert response.content is not None
    assert len(response.content) > 0

    # Should NOT have called any task tools (no mark_all_complete, no create_task)
    if response.tools:
        task_tool_names = {"mark_all_complete", "create_task", "execute_task", "execute_tasks_parallel"}
        called_tools = {t.tool_name for t in response.tools if t.tool_name}
        assert not called_tools.intersection(task_tool_names), (
            f"Expected no task tools for greeting, but got: {called_tools.intersection(task_tool_names)}"
        )


def test_tasks_mode_greeting_streaming(tasks_team):
    """Streaming a greeting should not produce task tool call events."""
    events = list(tasks_team.run("hello", stream=True, stream_events=True))

    # Should have content events
    has_content = False
    task_tool_calls = []
    iteration_count = 0

    for event in events:
        if hasattr(event, "content") and event.content:
            has_content = True
        if isinstance(event, ToolCallStartedEvent):
            if event.tool and event.tool.tool_name in {
                "mark_all_complete",
                "create_task",
                "execute_task",
            }:
                task_tool_calls.append(event.tool.tool_name)
        if isinstance(event, TaskIterationStartedEvent):
            iteration_count += 1

    assert has_content, "Expected content in streaming response"
    assert not task_tool_calls, f"Expected no task tool calls for greeting, but got: {task_tool_calls}"
    assert iteration_count <= 1, f"Expected at most 1 iteration for greeting, but got: {iteration_count}"


@pytest.mark.asyncio
async def test_tasks_mode_greeting_async(tasks_team):
    """Async greeting should also get a direct response."""
    response = await tasks_team.arun("hi there")

    assert response.content is not None
    assert len(response.content) > 0

    if response.tools:
        task_tool_names = {"mark_all_complete", "create_task", "execute_task", "execute_tasks_parallel"}
        called_tools = {t.tool_name for t in response.tools if t.tool_name}
        assert not called_tools.intersection(task_tool_names), (
            f"Expected no task tools for greeting, but got: {called_tools.intersection(task_tool_names)}"
        )


def test_tasks_mode_complex_request_creates_tasks(tasks_team):
    """A complex request should still trigger task decomposition (regression test)."""
    response = tasks_team.run(
        "Research the key differences between microservices and monolith architecture, "
        "then summarize the findings into 3 bullet points."
    )

    assert response.content is not None
    assert len(response.content) > 0

    # Should have called task tools for complex work
    assert response.tools is not None, "Expected task tools to be called for complex request"
    called_tools = {t.tool_name for t in response.tools if t.tool_name}
    # At minimum, should have created and executed at least one task
    assert "create_task" in called_tools or "execute_task" in called_tools, (
        f"Expected task creation/execution for complex request, but got: {called_tools}"
    )

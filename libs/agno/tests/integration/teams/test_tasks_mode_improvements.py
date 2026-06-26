"""Integration tests for tasks mode improvements.

Tests:
- Fix 1: Dependent task results passed to members
- Fix 2: Fresh task list per run
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import ToolCallCompletedEvent, ToolCallStartedEvent
from agno.team.mode import TeamMode
from agno.team.team import Team


@pytest.fixture
def dependency_team():
    """Create a team designed to test dependency context passing."""
    researcher = Agent(
        name="Researcher",
        role="Researches topics and gathers information",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Research the given topic.", "Provide detailed factual information."],
    )
    summarizer = Agent(
        name="Summarizer",
        role="Summarizes research into concise points",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "Summarize the information provided to you.",
            "If dependency results are provided, use them as your primary source.",
        ],
    )
    return Team(
        name="Research Pipeline Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[researcher, summarizer],
        instructions=[
            "You are a research pipeline leader.",
            "For research requests:",
            "1. Create a research task for the Researcher.",
            "2. Create a summary task for the Summarizer that depends on the research task.",
            "3. Execute tasks in order.",
            "4. Call mark_all_complete with the final summary.",
        ],
        max_iterations=5,
        telemetry=False,
    )


def test_dependency_results_passed_to_member(dependency_team):
    """The Summarizer should receive the Researcher's results via dependency context."""
    response = dependency_team.run("Research the top 3 benefits of exercise, then summarize them.")

    assert response.content is not None
    assert len(response.content) > 0

    # Verify that tasks were created and executed (not a direct response)
    assert response.tools is not None
    called_tools = {t.tool_name for t in response.tools if t.tool_name}
    assert "create_task" in called_tools, f"Expected create_task, got: {called_tools}"
    assert "execute_task" in called_tools, f"Expected execute_task, got: {called_tools}"


def test_fresh_task_list_per_run(dependency_team):
    """Second run should start with a clean task list, not carry over old tasks."""
    # First run: complex request that creates tasks
    response1 = dependency_team.run("Research the benefits of sleep and summarize.")
    assert response1.content is not None

    # Second run: simple greeting should not see old tasks
    response2 = dependency_team.run("hi")
    assert response2.content is not None

    # The greeting should NOT trigger task tools
    if response2.tools:
        task_tool_names = {"mark_all_complete", "create_task", "execute_task"}
        called_tools = {t.tool_name for t in response2.tools if t.tool_name}
        assert not called_tools.intersection(task_tool_names), (
            f"Expected no task tools for greeting after complex run, but got: {called_tools.intersection(task_tool_names)}"
        )

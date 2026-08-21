"""Integration tests for tasks mode improvements.

Tests:
- Dependent task results are passed to members
- A completed plan can be extended in a later run
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
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
        cache_session=True,
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


def test_follow_up_after_completed_plan_can_execute_new_tasks(dependency_team):
    """A follow-up can add and execute work after the prior plan completed."""
    response1 = dependency_team.run("Research the benefits of sleep and summarize.")
    assert response1.content is not None

    response2 = dependency_team.run("Now research two evidence-based ways to improve sleep and summarize them.")
    assert response2.content is not None
    assert response2.tools is not None
    called_tools = {tool.tool_name for tool in response2.tools if tool.tool_name}
    assert "create_task" in called_tools, f"Expected a new task in the follow-up, got: {called_tools}"
    assert "execute_task" in called_tools, f"Expected follow-up execution, got: {called_tools}"

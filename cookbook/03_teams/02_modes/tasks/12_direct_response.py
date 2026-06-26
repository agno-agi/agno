"""
Tasks Mode: Direct Response for Simple Messages
================================================

Demonstrates that `mode=tasks` handles simple messages gracefully by
responding directly, without creating tasks or calling mark_all_complete.

Complex requests still trigger full task decomposition and delegation.

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/12_direct_response.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.team import (
    RunContentEvent,
    TaskIterationStartedEvent,
    TaskStateUpdatedEvent,
    ToolCallStartedEvent,
)
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

planner = Agent(
    name="Planner",
    role="Creates outlines, plans, and structures for content",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=[
        "You are a planning specialist.",
        "Create clear, logical outlines and structures.",
    ],
)

writer = Agent(
    name="Writer",
    role="Writes polished content based on outlines or instructions",
    model=OpenAIResponses(id="gpt-4o-mini"),
    instructions=[
        "You are a skilled writer.",
        "Write clear, engaging content based on the provided plan.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Content Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-4o-mini"),
    members=[planner, writer],
    instructions=[
        "You are a content team leader with a Planner and a Writer.",
        "For content creation requests, create tasks for your members.",
        "For simple greetings or questions, respond directly.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=5,
)


# ---------------------------------------------------------------------------
# Helper: run with event tracking
# ---------------------------------------------------------------------------
def run_with_events(prompt: str) -> None:
    """Run a prompt and show what events are produced."""
    print(f"\n{'=' * 60}")
    print(f"Prompt: {prompt}")
    print("=" * 60)

    tool_calls = []
    iterations = 0

    for event in team.run(prompt, stream=True, stream_events=True):
        if isinstance(event, TaskIterationStartedEvent):
            iterations += 1
        elif isinstance(event, ToolCallStartedEvent):
            if event.tool and event.tool.tool_name:
                tool_calls.append(event.tool.tool_name)
                print(f"  [Tool: {event.tool.tool_name}]")
        elif isinstance(event, RunContentEvent):
            if event.content:
                print(event.content, end="", flush=True)
        elif isinstance(event, TaskStateUpdatedEvent):
            if event.goal_complete:
                print("\n  [Goal complete]")

    print(
        f"\n\n--- Stats: {iterations} iteration(s), tools called: {tool_calls or 'none'} ---\n"
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Scenario 1: Simple greeting - should respond directly, no tasks
    run_with_events("Hi there!")

    # Scenario 2: Simple question - should respond directly, no tasks
    run_with_events("What is the capital of France?")

    # Scenario 3: Complex request - should create and execute tasks
    run_with_events(
        "Create a short blog post outline about the benefits of remote work, "
        "then write the introduction paragraph."
    )

"""
Tasks Mode: Improvements Demo
==============================

Demonstrates four improvements to tasks mode:
1. Dependency context: dependent tasks receive completed dependency results
2. Bounded context: task_dependency_context_limit caps forwarded dependency results
3. Configurable previews: task_result_summary_limit controls task-state summaries
4. Replanning: edit_task and cancel_task update obsolete plans safely

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/13_task_improvements.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.team import (
    RunContentEvent,
    TaskCreatedEvent,
    TaskIterationStartedEvent,
    TaskStateUpdatedEvent,
    TaskUpdatedEvent,
    ToolCallStartedEvent,
)
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Researches topics and gathers detailed information",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a research specialist.",
        "Provide detailed, factual information on the given topic.",
    ],
)

writer = Agent(
    name="Writer",
    role="Writes polished content based on research and outlines",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a skilled writer.",
        "Use the provided research and context to write clear, engaging content.",
        "If dependency results are provided, use them as your primary source.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team (with increased result limit)
# ---------------------------------------------------------------------------

team = Team(
    name="Content Pipeline",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer],
    instructions=[
        "You lead a content pipeline with a Researcher and a Writer.",
        "For content requests:",
        "1. Create a research task for the Researcher.",
        "2. Create a writing task for the Writer that depends on the research task.",
        "3. Execute tasks in order.",
        "The Writer will automatically receive the Researcher's findings.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=5,
    task_result_summary_limit=1000,  # Show up to 1000 chars of results
    task_dependency_context_limit=4000,  # Bound the total dependency-result block
)


# ---------------------------------------------------------------------------
# Helper: run with event tracking
# ---------------------------------------------------------------------------
def run_with_events(prompt: str) -> None:
    """Run a prompt and show task lifecycle events."""
    print("\n" + "=" * 60)
    print(f"Prompt: {prompt}")
    print("=" * 60)

    for event in team.run(prompt, stream=True, stream_events=True):
        if isinstance(event, TaskIterationStartedEvent):
            print(f"\n--- Iteration {event.iteration}/{event.max_iterations} ---")
        elif isinstance(event, TaskCreatedEvent):
            deps = f" (depends on: {event.dependencies})" if event.dependencies else ""
            print(f"  + Task created: {event.title} -> {event.assignee}{deps}")
        elif isinstance(event, TaskUpdatedEvent):
            status_icon = {
                "pending": ".",
                "blocked": "#",
                "in_progress": "~",
                "completed": "v",
                "failed": "x",
                "cancelled": "-",
            }.get(event.status, "?")
            print(f"  [{status_icon}] {event.title}: {event.status}")
        elif isinstance(event, ToolCallStartedEvent):
            if event.tool and event.tool.tool_name in ("edit_task", "cancel_task"):
                print(f"  [Tool: {event.tool.tool_name}]")
        elif isinstance(event, RunContentEvent):
            if event.content:
                print(event.content, end="", flush=True)
        elif isinstance(event, TaskStateUpdatedEvent):
            if event.goal_complete:
                print("\n  [Goal complete]")

    print()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Scenario 1: Dependency context passing
    # The Writer should receive the Researcher's findings automatically
    print("\n[SCENARIO 1: Dependency context - Writer receives Researcher's results]")
    run_with_events(
        "Research the top 3 benefits of meditation, then write a short paragraph about them."
    )

    # Scenario 2: Configurable result limit
    # With task_result_summary_limit=1000, longer results are shown in task summaries
    print("\n[SCENARIO 2: Longer result summaries with task_result_summary_limit=1000]")
    run_with_events(
        "Research 5 key differences between Python and JavaScript, "
        "then write a comparison paragraph."
    )

    # Scenario 3: Replanning with edit_task and cancel_task
    # The leader should revise useful pending work, cancel obsolete work, and
    # create a replacement before marking the new plan complete.
    print("\n[SCENARIO 3: Edit and cancel obsolete tasks while replanning]")
    run_with_events(
        "Plan a short article about remote work. Create separate research, outline, and drafting tasks. "
        "Before execution, rename the outline task to focus on hybrid work, cancel the original drafting task "
        "as obsolete, create a replacement drafting task that depends on the revised outline, and complete the plan."
    )

"""
Plan-First Task Mode
====================

Demonstrates the plan-first behavior in `mode=tasks`, where the team leader:
1. Creates ALL tasks upfront in a planning phase
2. Then executes them in a separate execution phase

This gives frontends a clean initial TaskStateUpdated event with all tasks
in pending status, followed by execution events that transition tasks
through in_progress -> completed.

The script logs each tool call so you can verify that all create_task calls
happen before any execute_task / execute_tasks_parallel calls.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.team import (
    RunContentEvent,
    TaskIterationCompletedEvent,
    TaskIterationStartedEvent,
    TaskStateUpdatedEvent,
    TeamRunEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Researches topics and gathers factual information",
    model=Claude(id="claude-haiku-4-5-20251001"),
    instructions=[
        "Research the given topic thoroughly.",
        "Provide factual, well-organized information.",
    ],
)

writer = Agent(
    name="Writer",
    role="Writes polished content from research material",
    model=Claude(id="claude-haiku-4-5-20251001"),
    instructions=[
        "Write clear, engaging content based on the provided material.",
        "Follow any structure given to you.",
    ],
)

reviewer = Agent(
    name="Reviewer",
    role="Reviews content for accuracy and quality",
    model=Claude(id="claude-haiku-4-5-20251001"),
    instructions=[
        "Review the content for clarity, accuracy, and completeness.",
        "Provide the improved version directly.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Content Team",
    mode=TeamMode.tasks,
    plan_first=True,
    model=Claude(id="claude-sonnet-4-6"),
    members=[researcher, writer, reviewer],
    instructions=[
        "You are a content team leader.",
    ],
    markdown=True,
    max_iterations=10,
)


# ---------------------------------------------------------------------------
# Run with event streaming to show plan-first behavior
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("Plan-First Task Mode Demo")
    print("=" * 70)

    response_stream = team.run(
        "Write a short explainer on how large language models work, "
        "suitable for a non-technical audience.",
        stream=True,
        stream_events=True,
    )

    for event in response_stream:
        # -- Iteration boundaries --
        if isinstance(event, TaskIterationStartedEvent):
            print(f"\n{'=' * 70}")
            print(f"ITERATION {event.iteration}/{event.max_iterations} STARTED")
            print(f"{'=' * 70}")

        elif isinstance(event, TaskIterationCompletedEvent):
            print(f"\n{'=' * 70}")
            print(f"ITERATION {event.iteration}/{event.max_iterations} COMPLETED")
            print(f"{'=' * 70}")

        # -- Task state updates (the key event for frontends) --
        elif isinstance(event, TaskStateUpdatedEvent):
            print(f"\n{'~' * 70}")
            print("TASK STATE UPDATE")
            for t in event.tasks:
                status_icon = {
                    "pending": "[ ]",
                    "in_progress": "[~]",
                    "completed": "[x]",
                    "failed": "[!]",
                }.get(t.status, "[?]")
                print(
                    f"  {status_icon} {t.title} (assignee={t.assignee}, status={t.status})"
                )
            if event.goal_complete:
                print("  >> GOAL COMPLETE")
            print(f"{'~' * 70}")

        # -- Tool calls (shows planning vs execution) --
        elif isinstance(event, ToolCallStartedEvent):
            if event.tool and event.tool.tool_name:
                print(f"\n>> TOOL CALL: {event.tool.tool_name}", end="")
                if event.tool.tool_args:
                    # Show title for create_task, task_id for execute
                    args = event.tool.tool_args
                    if isinstance(args, dict):
                        if "title" in args:
                            print(f" (title={args['title']})", end="")
                        elif "task_id" in args:
                            print(f" (task_id={args['task_id']})", end="")
                        elif "task_ids" in args:
                            print(f" (task_ids={args['task_ids']})", end="")
                print()

        elif isinstance(event, ToolCallCompletedEvent):
            pass

        # -- Content from member agents --
        elif isinstance(event, AgentRunContentEvent):
            pass  # suppress member output to keep logs readable

        # -- Final team content --
        elif isinstance(event, RunContentEvent):
            if event.content:
                print(event.content, end="", flush=True)

        # -- Run lifecycle --
        elif hasattr(event, "event"):
            if event.event == TeamRunEvent.run_started.value:
                print("[Run Started]")
            elif event.event == TeamRunEvent.run_completed.value:
                print("\n[Run Completed]")

    print()


if __name__ == "__main__":
    main()

"""
Task Mode Streaming Events
==========================

Demonstrates how to consume streaming events programmatically in `mode=tasks`.

This example shows how to:
1. Use `stream=True` with `run()` to get an iterator of events
2. Handle task iteration events (started/completed)
3. Handle task state updates
4. Process content deltas as they arrive
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
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
    role="Researches topics and gathers information",
    model=OpenAIResponses(id="gpt-5.1"),
    instructions=["Research the given topic thoroughly.", "Provide factual information."],
)

summarizer = Agent(
    name="Summarizer",
    role="Summarizes information into concise points",
    model=OpenAIResponses(id="gpt-5.1"),
    instructions=["Create clear, concise summaries.", "Highlight key points."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Research Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.1"),
    members=[researcher, summarizer],
    instructions=[
        "You are a research team leader. Follow these steps exactly:",
        "1. Create a task for the Researcher to gather information.",
        "2. Execute the Researcher's task.",
        "3. Create a task for the Summarizer to summarize the research.",
        "4. Execute the Summarizer's task.",
        "5. Call mark_all_complete with a final summary when all tasks are done.",
    ],
    max_iterations=3,
)


# ---------------------------------------------------------------------------
# Sync streaming with event handling
# ---------------------------------------------------------------------------
def streaming_with_events() -> None:
    """Demonstrates sync streaming with programmatic event handling."""
    print("\n--- Sync Streaming with Event Handling ---\n")

    # Use stream=True to get an iterator of events
    response_stream = team.run(
        "What are the key benefits of microservices architecture?",
        stream=True,
        stream_events=True,
    )

    for event in response_stream:
        # Handle task iteration started - show all fields
        if isinstance(event, TaskIterationStartedEvent):
            print("\n" + "=" * 60)
            print("TASK ITERATION STARTED")
            print("=" * 60)
            print(f"  event:          {event.event}")
            print(f"  iteration:      {event.iteration}")
            print(f"  max_iterations: {event.max_iterations}")
            print("=" * 60)

        # Handle task iteration completed - show all fields
        elif isinstance(event, TaskIterationCompletedEvent):
            print("\n" + "=" * 60)
            print("TASK ITERATION COMPLETED")
            print("=" * 60)
            print(f"  event:          {event.event}")
            print(f"  iteration:      {event.iteration}")
            print(f"  max_iterations: {event.max_iterations}")
            print(f"  task_summary:   {event.task_summary[:100] if event.task_summary else None}...")
            print("=" * 60)

        # Handle task state updates - show all fields
        elif isinstance(event, TaskStateUpdatedEvent):
            print("\n" + "-" * 60)
            print("TASK STATE UPDATED")
            print("-" * 60)
            print(f"  event:         {event.event}")
            print(f"  task_summary:  {event.task_summary[:100] if event.task_summary else None}...")
            print(f"  goal_complete: {event.goal_complete}")
            print("-" * 60)

        # Handle tool call events (shows when tasks are being executed)
        elif isinstance(event, ToolCallStartedEvent):
            if event.tool and event.tool.tool_name:
                print(f"\n[Tool: {event.tool.tool_name}]", end="")

        elif isinstance(event, ToolCallCompletedEvent):
            pass  # Tool completed

        # Handle member agent content streaming
        elif isinstance(event, AgentRunContentEvent):
            if event.content:
                print(event.content, end="", flush=True)

        # Handle team content deltas
        elif isinstance(event, RunContentEvent):
            if event.content:
                print(event.content, end="", flush=True)

        # Handle other events by their event type
        elif hasattr(event, "event"):
            if event.event == TeamRunEvent.run_started.value:
                print("[Run Started]")
            elif event.event == TeamRunEvent.run_completed.value:
                print("\n[Run Completed]")

    print()


if __name__ == "__main__":
    streaming_with_events()

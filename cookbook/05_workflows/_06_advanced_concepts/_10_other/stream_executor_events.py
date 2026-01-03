"""
Example: Using stream_executor_events=False for cleaner workflow streaming.

This filters out internal executor events (AgentRunEvent, ToolCallEvent, etc.)
while keeping high-level workflow and step events.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

agent = Agent(
    name="ResearchAgent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful research assistant. Be concise.",
)

workflow = Workflow(
    name="Research Workflow",
    steps=[Step(name="Research", agent=agent)],
    stream=True,
    stream_executor_events=False,  # Filter out internal executor events
)


def main():
    print("\n" + "=" * 70)
    print("Workflow Streaming Example: stream_executor_events=False")
    print("=" * 70)
    print(
        "\nThis will show only workflow and step events and will not yield RunContent and TeamRunContent events"
    )
    print("filtering out internal agent/team events for cleaner output.\n")

    # Run workflow and display events
    for event in workflow.run(
        "What is Python?",
        stream=True,
        stream_events=True,
    ):
        event_name = event.event if hasattr(event, "event") else type(event).__name__
        print(f"  → {event_name}")


if __name__ == "__main__":
    main()

"""
Executor Events
===============

Demonstrates filtering internal executor events during streamed workflow runs.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="ResearchAgent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful research assistant. Be concise.",
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Research Workflow",
    steps=[Step(name="Research", agent=agent)],
    stream=True,
    stream_executor_events=False,
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
def main() -> None:
    print("\n" + "=" * 70)
    print("Workflow Streaming Example: stream_executor_events=False")
    print("=" * 70)
    print(
        "\nThis will show only workflow and step events and will not yield RunContent and TeamRunContent events"
    )
    print("Filtering out internal agent/team events for cleaner output.\n")

    for event in workflow.run(
        "What is Python?",
        stream=True,
        stream_events=True,
    ):
        event_name = event.event if hasattr(event, "event") else type(event).__name__
        print(f"  -> {event_name}")


if __name__ == "__main__":
    main()

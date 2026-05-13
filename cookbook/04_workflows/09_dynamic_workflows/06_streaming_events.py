"""Dynamic Workflow - Live event streaming.

When you stream a dynamic workflow, per-spawn events flow through the workflow's stream
in real time. This is what powers live "watch the plan grow" UIs.

What you get on the stream:
- `WorkflowStartedEvent` / `WorkflowCompletedEvent` at the boundaries.
- `StepSpawnedEvent` each time the driver invents a new specialist (role, instructions,
  tools).
- `StepStartedEvent` / `StepCompletedEvent` for each spawn's lifecycle.
- `RunStartedEvent` / `RunCompletedEvent` for the spawned agent itself.
- `RunContentEvent` token-by-token as the spawned agent generates output.
- `ModelRequestStartedEvent` / `ModelRequestCompletedEvent` around model calls.

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/06_streaming_events.py
"""

from agno.models.openai import OpenAIResponses
from agno.run.agent import RunContentEvent
from agno.run.workflow import StepSpawnedEvent
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import DynamicWorkflowDriver, Workflow


def main() -> None:
    driver = DynamicWorkflowDriver(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions="Produce a short HN briefing on the user's topic. 2-3 spawns is plenty.",
        allowed_tools=[HackerNewsTools()],
        max_steps=4,
    )

    workflow = Workflow(
        name="DynamicStreamingBriefing",
        steps=driver,
        stream_events=True,
    )

    print("Streaming events as the driver expands the plan...\n")

    for event in workflow.run(
        input="What is HN saying about local LLM inference?",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, StepSpawnedEvent):
            print(f"  [SPAWN {event.iteration}] role={event.role!r} tools={event.tool_names!r}")
        if isinstance(event, RunContentEvent):
            continue
        else:
            # Compact one-line view for everything else
            kind = type(event).__name__.removesuffix("Event")
            print(f"  [{kind}]")


if __name__ == "__main__":
    main()

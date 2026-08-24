"""
Background SSE Stream
=====================

Demonstrates running a workflow in background SSE streaming mode (background=True, stream=True).

This is the default transport for AgentOS workflow runs - events stream via SSE
and the workflow survives client disconnections.

Tests that metadata flows correctly through the SSE dispatch path.
"""

import asyncio
from typing import Any, Dict, Optional

from agno.db.in_memory import InMemoryDb
from agno.run.base import RunContext
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow


async def research_step(step_input: StepInput, run_context: RunContext = None) -> str:
    """Simulate research that uses metadata for context."""
    metadata = run_context.metadata if run_context else {}
    user_context = metadata.get("user_context", "unknown")
    priority = metadata.get("priority", "normal")

    return f"Research completed for context: {user_context} (priority: {priority})"


async def planning_step(step_input: StepInput, run_context: RunContext = None) -> str:
    """Simulate planning that uses dependencies."""
    deps = run_context.dependencies if run_context else {}
    config = deps.get("config", {})

    previous = step_input.previous_step_content or "No previous content"
    return f"Plan created based on: {previous}. Config: {config}"


# Create workflow with default metadata
workflow = Workflow(
    name="SSE Stream Demo",
    description="Demonstrates SSE background streaming with metadata",
    metadata={"workflow_default": "base_value"},
    dependencies={"config": {"max_items": 10}},
    db=InMemoryDb(),
    steps=[
        Step(name="Research", executor=research_step),
        Step(name="Planning", executor=planning_step),
    ],
)


async def main():
    print("Background SSE Stream Demo")
    print("=" * 60)
    print("Testing: background=True, stream=True (SSE path)")
    print("This is the default transport for AgentOS workflow runs")
    print("=" * 60)

    # Run with background=True, stream=True (SSE path)
    # Pass call-site metadata that merges with workflow defaults
    stream = workflow.arun(
        input="Plan a content strategy for AI trends",
        background=True,
        stream=True,
        metadata={
            "user_context": "marketing_team",
            "priority": "high",
            "request_id": "req-12345",
        },
        add_dependencies_to_context=True,
    )

    print("\nStreaming SSE events:")
    print("-" * 40)

    event_count = 0
    run_id = None

    async for sse_chunk in stream:
        event_count += 1

        # Extract run_id from first event
        if run_id is None and '"run_id"' in sse_chunk:
            import json
            for line in sse_chunk.splitlines():
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                        run_id = payload.get("run_id")
                    except:
                        pass

        # Show event type
        if '"event":' in sse_chunk:
            import json
            for line in sse_chunk.splitlines():
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                        event_type = payload.get("event", "unknown")
                        print(f"  Event {event_count}: {event_type}")
                    except:
                        print(f"  Event {event_count}: (parse error)")

    print("-" * 40)
    print(f"Total events received: {event_count}")

    # Get final result
    if run_id:
        await asyncio.sleep(0.5)  # Let background task finish
        result = workflow.get_run(run_id)
        if result:
            print(f"\nFinal Status: {result.status}")
            print(f"Final Content:\n{result.content}")

    print("\n" + "=" * 60)
    print("SUCCESS: SSE background streaming completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

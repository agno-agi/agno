"""
Remote Workflow
===============

Demonstrates executing a workflow hosted on a remote server using `RemoteWorkflow`.
"""

import asyncio
import os

from agno.workflow import RemoteWorkflow

# ---------------------------------------------------------------------------
# Create Remote Workflow
# ---------------------------------------------------------------------------
remote_workflow = RemoteWorkflow(
    base_url=os.getenv("AGNO_REMOTE_BASE_URL", "http://localhost:7777"),
    workflow_id=os.getenv("AGNO_REMOTE_WORKFLOW_ID", "qa-workflow"),
)


async def run_remote_examples() -> None:
    print("Remote workflow configuration")
    print(f"  Base URL: {remote_workflow.base_url}")
    print(f"  Workflow ID: {remote_workflow.id}")

    try:
        response = await remote_workflow.arun(
            input="Summarize the latest progress in AI coding assistants.",
            stream=False,
        )
        print("\nNon-streaming response preview")
        print(f"  Run ID: {response.run_id}")
        print(f"  Content: {str(response.content)[:240]}")
    except Exception as exc:
        print("\nRemote run failed.")
        print("  Ensure AgentOS is running and the workflow ID exists.")
        print(f"  Error: {exc}")
        return

    try:
        print("\nStreaming response preview")
        stream = remote_workflow.arun(
            input="List three practical use-cases for autonomous workflows.",
            stream=True,
            stream_events=True,
        )
        async for event in stream:
            event_name = getattr(event, "event", type(event).__name__)
            content = getattr(event, "content", None)
            if content:
                print(content, end="", flush=True)
            elif event_name:
                print(f"\n[{event_name}]")
        print()
    except Exception as exc:
        print("\nStreaming run failed.")
        print(f"  Error: {exc}")


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(run_remote_examples())

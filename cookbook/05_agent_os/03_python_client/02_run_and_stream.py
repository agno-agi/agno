"""Run an agent through AgentOS with normal and streaming responses.

The stream is parsed into typed Agno events so applications can handle
content, tools, completion, and errors explicitly.

Prerequisites: start ``_server.py`` and set OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/02_run_and_stream.py
Try: watch the calculator tool events arrive before the final content.
"""

import asyncio

from agno.client import AgentOSClient
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)

BASE_URL = "http://localhost:7778"
AGENT_ID = "assistant"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


async def cancel_active_run(client: AgentOSClient, run_id: str) -> None:
    """Cancel an active agent run."""
    await client.cancel_agent_run(AGENT_ID, run_id)


async def run_examples() -> None:
    """Run one complete response and one typed event stream."""
    client = AgentOSClient(base_url=BASE_URL)

    response = await client.run_agent(
        agent_id=AGENT_ID,
        message="What is 17 multiplied by 23? Use the calculator.",
    )
    print(f"Non-streaming run: {response.run_id}")
    print(response.content)

    print("\nStreaming response:")
    async for event in client.run_agent_stream(
        agent_id=AGENT_ID,
        message="Use the calculator to add 41 and 1, then explain the result.",
    ):
        if isinstance(event, RunStartedEvent):
            print(f"Run started: {event.run_id}")
        elif isinstance(event, ToolCallStartedEvent):
            tool_name = event.tool.tool_name if event.tool else "unknown"
            print(f"\nTool started: {tool_name}")
        elif isinstance(event, ToolCallCompletedEvent):
            tool_name = event.tool.tool_name if event.tool else "unknown"
            print(f"Tool completed: {tool_name}")
        elif isinstance(event, RunContentEvent) and event.content is not None:
            print(event.content, end="", flush=True)
        elif isinstance(event, RunCompletedEvent):
            print(f"\nRun completed: {event.run_id}")
        elif isinstance(event, RunErrorEvent):
            raise RuntimeError(event.content or "Agent run failed")

    print(
        "\nTeams and workflows use the same pattern through "
        "run_team/run_team_stream and run_workflow/run_workflow_stream."
    )
    print("Cancel an active run with await client.cancel_agent_run(agent_id, run_id).")


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_examples())

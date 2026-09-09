"""
Call and stream an Agent on another AgentOS
===========================================

RemoteAgent presents a remote AgentOS Agent through the same asynchronous run
shape used by local Agno components.

Prerequisites: start `servers/agentos_server.py` and set OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/01_remote_agent.py
Try: change either arithmetic prompt and observe the remote calculator call
"""

import asyncio

from agno.agent import RemoteAgent
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunStartedEvent,
)

BASE_URL = "http://127.0.0.1:7780"

# ---------------------------------------------------------------------------
# Create Remote Agent
# ---------------------------------------------------------------------------

remote_assistant = RemoteAgent(
    base_url=BASE_URL,
    agent_id="assistant-agent",
)

# ---------------------------------------------------------------------------
# Run Remote Agent
# ---------------------------------------------------------------------------


async def run_remote_agent() -> None:
    """Run one complete response and one typed remote stream."""
    response = await remote_assistant.arun(
        "Use the calculator to multiply 17 by 23.",
        session_id="remote-agent-session",
    )
    print(f"Non-streaming run: {response.run_id}")
    print(response.content)

    print("\nStreaming response:")
    async for event in remote_assistant.arun(
        "Use the calculator to add 41 and 1, then explain the result.",
        session_id="remote-agent-session",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, RunStartedEvent):
            print(f"Run started: {event.run_id}")
        elif isinstance(event, RunContentEvent) and event.content is not None:
            print(event.content, end="", flush=True)
        elif isinstance(event, RunCompletedEvent):
            print(f"\nRun completed: {event.run_id}")
        elif isinstance(event, RunErrorEvent):
            raise RuntimeError(event.content or "Remote Agent run failed")


if __name__ == "__main__":
    asyncio.run(run_remote_agent())

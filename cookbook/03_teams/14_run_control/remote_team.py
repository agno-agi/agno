"""
Remote Team
=============================

Demonstrates calling and streaming a team hosted on a remote AgentOS instance.
"""

import asyncio
import socket

from agno.exceptions import RemoteServerUnavailableError
from agno.team import RemoteTeam

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
remote_team = RemoteTeam(
    base_url="http://localhost:7778",
    team_id="research-team",
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def remote_team_example() -> None:
    response = await remote_team.arun(
        "What is the capital of France?",
        user_id="user-123",
        session_id="session-456",
    )
    print(response.content)


async def remote_streaming_example() -> None:
    async for chunk in remote_team.arun(
        "Tell me a 2 sentence horror story",
        session_id="session-456",
        user_id="user-123",
        stream=True,
    ):
        if hasattr(chunk, "content") and chunk.content:
            print(chunk.content, end="", flush=True)


async def main() -> None:
    print("=" * 60)
    print("RemoteTeam Examples")
    print("=" * 60)

    print("\n1. Remote Team Example:")
    await remote_team_example()

    print("\n2. Remote Streaming Example:")
    await remote_streaming_example()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        socket.gaierror,
        RemoteServerUnavailableError,
    ) as exc:
        print(
            "\nRemoteTeam server is not available. Start a remote AgentOS instance at "
            "http://localhost:7778 and rerun this cookbook."
        )
        print(f"Original error: {exc}")

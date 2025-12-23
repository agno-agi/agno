"""
Examples demonstrating AgentOSRunner for remote execution.

Run `agent_os_setup.py` to start the remote AgentOS instance.
"""

import asyncio

from agno.team import RemoteTeam


async def remote_agent_example():
    """Call a remote agent hosted on another AgentOS instance."""
    # Create a runner that points to a remote agent
    team = RemoteTeam(
        base_url="http://localhost:7778",
        team_id="research-team",
    )

    response = await team.arun(
        "What is the capital of France?",
        user_id="user-123",
        session_id="session-456",
    )
    print(response.content)


async def remote_streaming_example():
    """Stream responses from a remote agent."""
    team = RemoteTeam(
        base_url="http://localhost:7778",
        team_id="research-team",
    )

    async for chunk in team.arun(
        "Tell me a 2 sentence horror story",
        session_id="session-456",
        user_id="user-123",
        stream=True,
    ):
        if hasattr(chunk, "content") and chunk.content:
            print(chunk.content, end="", flush=True)


if __name__ == "__main__":
    print("=" * 60)
    print("RemoteTeam Examples")
    print("=" * 60)

    # Run examples
    # Note: Remote examples require a running AgentOS instance

    print("\n1. Remote Team Example:")
    # asyncio.run(remote_agent_example())

    print("\n2. Remote Streaming Example:")
    asyncio.run(remote_streaming_example())

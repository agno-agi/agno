"""
Running Teams with AgentOSClient

This example demonstrates how to execute team runs using
AgentOSClient, including both streaming and non-streaming responses.

Prerequisites:
1. Start an AgentOS server with a team configured
2. Run this script: python 06_run_teams.py
"""

import asyncio
import json

from agno.os.client import AgentOSClient


async def run_team_non_streaming():
    """Execute a non-streaming team run."""
    print("=" * 60)
    print("Non-Streaming Team Run")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available teams
        config = await client.get_config()
        if not config.teams:
            print("No teams available")
            return

        team_id = config.teams[0].id
        print(f"Running team: {team_id}")

        # Execute the team
        result = await client.run_team(
            team_id=team_id,
            message="What is the capital of France and what is 15 * 7?",
        )

        print(f"\nRun ID: {result.run_id}")
        print(f"Content: {result.content}")


async def run_team_streaming():
    """Execute a streaming team run."""
    print("\n" + "=" * 60)
    print("Streaming Team Run")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available teams
        config = await client.get_config()
        if not config.teams:
            print("No teams available")
            return

        team_id = config.teams[0].id
        print(f"Streaming from team: {team_id}")
        print("\nResponse: ", end="", flush=True)

        # Stream the response
        async for line in client.stream_team_run(
            team_id=team_id,
            message="Tell me about Python programming in 2 sentences.",
        ):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if data.get("event") == "RunContent":
                        content = data.get("content", "")
                        print(content, end="", flush=True)
                except json.JSONDecodeError:
                    pass

        print("\n")


async def run_team_with_session():
    """Execute team runs within a session for multi-turn conversations."""
    print("=" * 60)
    print("Multi-Turn Team Conversation with Session")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available teams
        config = await client.get_config()
        if not config.teams:
            print("No teams available")
            return

        team_id = config.teams[0].id

        # Create a session for the team
        session = await client.create_session(
            team_id=team_id,
            user_id="example-user",
        )
        print(f"Created session: {session.session_id}")

        # First message - simple calculation
        print("\nUser: Calculate 25 + 17.")
        try:
            result1 = await client.run_team(
                team_id=team_id,
                message="Calculate 25 + 17.",
                session_id=session.session_id,
            )
            print(f"Team: {result1.content}")

            # Second message
            print("\nUser: Now multiply the result by 2.")
            result2 = await client.run_team(
                team_id=team_id,
                message="Now multiply the result by 2.",
                session_id=session.session_id,
            )
            print(f"Team: {result2.content}")
        except Exception as e:
            print(f"Error (team may have timed out): {type(e).__name__}")


async def main():
    await run_team_non_streaming()
    await run_team_streaming()
    await run_team_with_session()


if __name__ == "__main__":
    asyncio.run(main())


"""
Running Teams with AgentOSClient

This example demonstrates how to execute team runs using
AgentOSClient, including both streaming and non-streaming responses.

Prerequisites:
1. Start an AgentOS server with a team configured
2. Run this script: python 06_run_teams.py
"""

import asyncio

from agno.client import AgentOSClient


async def run_team_non_streaming():
    """Execute a non-streaming team run."""
    print("=" * 60)
    print("Non-Streaming Team Run")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available teams
    config = await client.aget_config()
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

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available teams
    config = await client.aget_config()
    if not config.teams:
        print("No teams available")
        return

    team_id = config.teams[0].id
    print(f"Streaming from team: {team_id}")
    print("\nResponse: ", end="", flush=True)

    from agno.run.team import RunCompletedEvent, RunContentEvent

    # Stream the response
    async for event in client.run_team_stream(
        team_id=team_id,
        message="Tell me about Python programming in 2 sentences.",
    ):
        # Handle different event types
        if isinstance(event, RunContentEvent):
            print(event.content, end="", flush=True)
        elif isinstance(event, RunCompletedEvent):
            # Run completed - could access event.run_id here if needed
            pass

    print("\n")


async def main():
    await run_team_non_streaming()
    await run_team_streaming()


if __name__ == "__main__":
    asyncio.run(main())

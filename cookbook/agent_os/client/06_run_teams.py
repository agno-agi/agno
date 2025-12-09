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

        from agno.run.team import RunContentEvent, RunCompletedEvent

        # Stream the response
        async for event in client.stream_team_run(
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


async def run_team_with_session():
    """Execute team runs within a session.

    Note: Teams coordinate multiple agents and may not maintain
    conversation context like a single agent would.
    """
    print("=" * 60)
    print("Team Run with Session")
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

        # Run a query that requires team coordination
        print("\nUser: Research what Python is and calculate 100 / 4.")
        try:
            result = await client.run_team(
                team_id=team_id,
                message="Research what Python is and calculate 100 / 4.",
                session_id=session.session_id,
            )
            print(f"Team: {result.content}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


async def main():
    await run_team_non_streaming()
    await run_team_streaming()
    await run_team_with_session()


if __name__ == "__main__":
    asyncio.run(main())

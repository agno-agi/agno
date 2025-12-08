"""
Running Agents with AgentOSClient

This example demonstrates how to execute agent runs using
AgentOSClient, including both streaming and non-streaming responses.

Prerequisites:
1. Start an AgentOS server with an agent
2. Run this script: python 02_run_agents.py
"""

import asyncio
import json

from agno.os.client import AgentOSClient


async def run_agent_non_streaming():
    """Execute a non-streaming agent run."""
    print("=" * 60)
    print("Non-Streaming Agent Run")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available agents
        config = await client.get_config()
        if not config.agents:
            print("No agents available")
            return

        agent_id = config.agents[0].id
        print(f"Running agent: {agent_id}")

        # Execute the agent
        result = await client.run_agent(
            agent_id=agent_id,
            message="What is 2 + 2? Explain your answer briefly.",
        )

        print(f"\nRun ID: {result.run_id}")
        print(f"Content: {result.content}")
        print(
            f"Tokens: {result.metrics.get('total_tokens') if result.metrics else 'N/A'}"
        )


async def run_agent_streaming():
    """Execute a streaming agent run."""
    print("\n" + "=" * 60)
    print("Streaming Agent Run")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available agents
        config = await client.get_config()
        if not config.agents:
            print("No agents available")
            return

        agent_id = config.agents[0].id
        print(f"Streaming from agent: {agent_id}")
        print("\nResponse: ", end="", flush=True)

        # Stream the response
        full_content = ""
        async for line in client.stream_agent_run(
            agent_id=agent_id,
            message="Tell me a short joke.",
        ):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if data.get("event") == "RunContent":
                        content = data.get("content", "")
                        print(content, end="", flush=True)
                        full_content += content
                except json.JSONDecodeError as e:
                    print(
                        f"Warning: Failed to decode JSON from line: {line[6:]}. Error: {e}"
                    )

        print("\n")


async def run_agent_with_session():
    """Execute agent runs within a session for multi-turn conversations."""
    print("=" * 60)
    print("Multi-Turn Conversation with Session")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Get available agents
        config = await client.get_config()
        if not config.agents:
            print("No agents available")
            return

        agent_id = config.agents[0].id

        # Create a session for multi-turn conversation
        session = await client.create_session(
            agent_id=agent_id,
            user_id="example-user",
        )
        print(f"Created session: {session.session_id}")

        # First message
        print("\nUser: My name is Alice.")
        result1 = await client.run_agent(
            agent_id=agent_id,
            message="My name is Alice.",
            session_id=session.session_id,
        )
        print(f"Assistant: {result1.content}")

        # Second message - agent should remember the context
        print("\nUser: What is my name?")
        result2 = await client.run_agent(
            agent_id=agent_id,
            message="What is my name?",
            session_id=session.session_id,
        )
        print(f"Assistant: {result2.content}")

        # Get session runs
        runs = await client.get_session_runs(session_id=session.session_id)
        print(f"\nSession has {len(runs)} runs")


async def main():
    await run_agent_non_streaming()
    await run_agent_streaming()
    await run_agent_with_session()


if __name__ == "__main__":
    asyncio.run(main())

"""
Basic A2A Messaging with A2AClient

This example demonstrates simple message sending and receiving
using the A2A protocol.

Prerequisites:
1. Start an AgentOS server with A2A interface:
   python cookbook/agent_os/interfaces/a2a/basic.py

2. Run this script:
   python cookbook/agent_os/a2a_client/01_basic_messaging.py
"""

import asyncio

from agno.a2a import A2AClient


async def main():
    print("=" * 60)
    print("Basic A2A Messaging")
    print("=" * 60)

    # Connect to any A2A-compatible server
    async with A2AClient("http://localhost:7777") as client:
        # Send a simple message
        print("\nSending message to agent...")

        result = await client.send_message(
            agent_id="basic-agent",
            message="What is the capital of France?",
        )

        print(f"\nTask ID: {result.task_id}")
        print(f"Context ID: {result.context_id}")
        print(f"Status: {result.status}")
        print(f"\nResponse: {result.content}")

        # Check status properties
        if result.is_completed:
            print("\nTask completed successfully!")
        elif result.is_failed:
            print("\nTask failed!")


async def with_user_id():
    """Send message with user identification."""
    print("\n" + "=" * 60)
    print("A2A Messaging with User ID")
    print("=" * 60)

    async with A2AClient("http://localhost:7777") as client:
        result = await client.send_message(
            agent_id="basic-agent",
            message="Remember my name is Alice.",
            user_id="alice-123",
        )

        print(f"\nResponse: {result.content}")


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(with_user_id())


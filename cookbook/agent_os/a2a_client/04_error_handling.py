"""
Error Handling with A2AClient

This example demonstrates how to handle various error scenarios
when using the A2A protocol.

Prerequisites:
1. Start an AgentOS server with A2A interface:
   python cookbook/agent_os/interfaces/a2a/basic.py

2. Run this script:
   python cookbook/agent_os/a2a_client/04_error_handling.py
"""

import asyncio

from agno.a2a import (
    A2AAgentNotFoundError,
    A2AClient,
    A2AConnectionError,
    A2ARequestError,
    A2ATaskFailedError,
    A2ATimeoutError,
)


async def handle_agent_not_found():
    """Handle case when agent doesn't exist."""
    print("=" * 60)
    print("Handling Agent Not Found")
    print("=" * 60)

    async with A2AClient("http://localhost:7777") as client:
        try:
            await client.send_message(
                agent_id="nonexistent-agent",
                message="Hello",
            )
        except A2AAgentNotFoundError as e:
            print(f"\nAgent not found: {e.agent_id}")
            print("Suggestion: Check available agents on the server")


async def handle_connection_error():
    """Handle case when server is unreachable."""
    print("\n" + "=" * 60)
    print("Handling Connection Error")
    print("=" * 60)

    # Try to connect to a server that doesn't exist
    async with A2AClient("http://localhost:9999") as client:
        try:
            await client.send_message(
                agent_id="any-agent",
                message="Hello",
            )
        except A2AConnectionError as e:
            print(f"\nConnection failed: {e}")
            print("Suggestion: Check if the A2A server is running")


async def handle_timeout():
    """Handle request timeout."""
    print("\n" + "=" * 60)
    print("Handling Timeout")
    print("=" * 60)

    # Use a very short timeout
    async with A2AClient("http://localhost:7777", timeout=0.001) as client:
        try:
            await client.send_message(
                agent_id="basic-agent",
                message="This might timeout",
            )
        except A2ATimeoutError as e:
            print(f"\nRequest timed out: {e}")
            print("Suggestion: Increase timeout or check server performance")
        except A2AConnectionError:
            print("\nConnection error (timeout too short to connect)")


async def comprehensive_error_handling():
    """Demonstrate comprehensive error handling pattern."""
    print("\n" + "=" * 60)
    print("Comprehensive Error Handling Pattern")
    print("=" * 60)

    async def safe_send_message(client, agent_id: str, message: str):
        """Safely send a message with proper error handling."""
        try:
            result = await client.send_message(
                agent_id=agent_id,
                message=message,
            )
            return result

        except A2AAgentNotFoundError as e:
            print(f"Error: Agent '{e.agent_id}' not found")
            return None

        except A2ATaskFailedError as e:
            print(f"Error: Task failed - {e.reason}")
            return None

        except A2ARequestError as e:
            print(f"Error: Request failed ({e.status_code}) - {e.detail}")
            return None

        except A2ATimeoutError:
            print("Error: Request timed out")
            return None

        except A2AConnectionError as e:
            print(f"Error: Connection failed - {e}")
            return None

    async with A2AClient("http://localhost:7777") as client:
        print("\nTrying valid agent...")
        result = await safe_send_message(client, "basic-agent", "Hello!")
        if result:
            print(f"Success: {result.content[:50]}...")

        print("\nTrying invalid agent...")
        result = await safe_send_message(client, "invalid-agent", "Hello!")
        if result:
            print(f"Success: {result.content}")


if __name__ == "__main__":
    asyncio.run(handle_agent_not_found())
    asyncio.run(handle_connection_error())
    asyncio.run(handle_timeout())
    asyncio.run(comprehensive_error_handling())


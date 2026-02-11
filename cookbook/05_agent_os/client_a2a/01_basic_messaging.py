"""
Basic A2A Messaging with A2AClient

This example demonstrates simple message sending with user identification
using the A2A protocol.

Prerequisites:
1. Start an AgentOS server with A2A interface:
   python cookbook/06_agent_os/client_a2a/servers/agno_server.py

2. Run this script:
   python cookbook/06_agent_os/client_a2a/01_basic_messaging.py
"""

import asyncio

from agno.client.a2a import A2AClient

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


async def main():
    """Send message with user identification."""
    print("=" * 60)
    print("A2A Messaging with User ID")
    print("=" * 60)

    client = A2AClient("http://localhost:7003/a2a/agents/basic-agent")
    result = await client.send_message(
        message="Remember my name is Alice.",
        user_id="alice-123",
    )

    print(f"\nTask ID: {result.task_id}")
    print(f"Context ID: {result.context_id}")
    print(f"Status: {result.status}")
    print(f"\nResponse: {result.content}")

    if result.is_completed:
        print("\nTask completed successfully!")
    elif result.is_failed:
        print("\nTask failed!")


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())

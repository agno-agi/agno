"""Connect Agno A2AClient to Google ADK A2A Server.

This example demonstrates cross-framework A2A communication:
Agno client -> Google ADK server

Prerequisites:
    1. Install dependencies:
       uv pip install agno httpx google-adk uvicorn

    2. Set your Google API key:
       export GOOGLE_API_KEY=your_key

    3. Start Google ADK server:
       python cookbook/06_agent_os/client_a2a/servers/google_adk_server.py

    4. Run this script:
       python cookbook/06_agent_os/client_a2a/05_connect_to_google_adk.py
"""

import asyncio

from agno.client.a2a import A2AClient

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Google ADK server URL
ADK_SERVER_URL = "http://localhost:8001/"


async def basic_messaging():
    """Send a simple message to the Google ADK agent."""
    print("=" * 60)
    print("Basic Messaging with Google ADK")
    print("=" * 60)

    # Connect to Google ADK server
    # Note: json_rpc_endpoint="/" enables pure JSON-RPC mode for Google ADK
    client = A2AClient(ADK_SERVER_URL, protocol="json-rpc")
    print("\nSending message...")

    result = await client.send_message(
        message="Tell me an interesting fact about the moon.",
    )

    print(f"\nTask ID: {result.task_id}")
    print(f"Context ID: {result.context_id}")
    print(f"Status: {result.status}")
    print(f"\nResponse:\n{result.content}")

    if result.is_completed:
        print("\nTask completed successfully!")
    elif result.is_failed:
        print("\nTask failed!")


async def with_user_id():
    """Send message with user identification."""
    print("\n" + "=" * 60)
    print("Messaging with User ID")
    print("=" * 60)

    client = A2AClient(ADK_SERVER_URL, protocol="json-rpc")
    result = await client.send_message(
        message="What's an interesting fact about Mars?",
        user_id="user-123",
    )

    print(f"\nResponse:\n{result.content}")


async def get_agent_info():
    """Try to get the agent card (capability discovery)."""
    print("\n" + "=" * 60)
    print("Agent Card Discovery")
    print("=" * 60)

    client = A2AClient(ADK_SERVER_URL, protocol="json-rpc")
    try:
        card = await client.get_agent_card()
        if card:
            print(f"\nAgent Name: {card.name}")
            print(f"Description: {card.description}")
            print(f"Version: {card.version}")
            print(f"Capabilities: {card.capabilities}")
        else:
            print("\nAgent card not available")
    except Exception as e:
        print(f"\nAgent card not available: {e}")
        print("(This is optional - not all A2A servers provide agent cards)")


async def main():
    await basic_messaging()
    await with_user_id()
    await get_agent_info()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())

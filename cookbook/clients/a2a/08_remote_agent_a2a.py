"""Using RemoteAgent with A2A protocol.

This example demonstrates how to use RemoteAgent with the A2A protocol
to communicate with any A2A-compatible agent server.

The key advantage is that you use the same familiar RemoteAgent interface
whether you're connecting to:
- Agno AgentOS servers (default protocol)
- Agno servers with A2A interface
- Google ADK servers
- Any other A2A-compatible server

Prerequisites:
    1. Install dependencies:
       pip install agno httpx google-adk uvicorn

    2. Set your Google API key:
       export GOOGLE_API_KEY=your_key

    3. Start Google ADK server:
       python cookbook/agent_os/a2a_client/servers/google_adk_server.py

    4. Run this script:
       python cookbook/agent_os/a2a_client/08_remote_agent_a2a.py

Protocol Options:
    - protocol="agentos" (default): Use Agno's proprietary REST API
    - protocol="a2a": Use A2A protocol for cross-framework communication
"""

import asyncio

from agno.agent import RemoteAgent
from agno.run.agent import RunContentEvent

# Google ADK server settings
ADK_SERVER_URL = "http://localhost:8001"
AGENT_ID = "facts_agent"


async def basic_messaging():
    """Send a simple message using RemoteAgent with A2A protocol."""
    print("=" * 60)
    print("RemoteAgent with A2A Protocol - Basic Messaging")
    print("=" * 60)

    # Create RemoteAgent with A2A protocol
    # json_rpc_endpoint="/" is required for Google ADK servers
    agent = RemoteAgent(
        base_url=ADK_SERVER_URL,
        agent_id=AGENT_ID,
        protocol="a2a",
        json_rpc_endpoint="/",  # Google ADK uses root endpoint
    )

    print(f"\nSending message to {AGENT_ID} via A2A protocol...")

    # Use the same arun() interface as local agents
    result = await agent.arun("Tell me an interesting fact about the moon.")

    print(f"\nRun ID: {result.run_id}")
    print(f"Session ID: {result.session_id}")
    print(f"\nResponse:\n{result.content}")


async def streaming_response():
    """Stream responses using RemoteAgent with A2A protocol."""
    print("\n" + "=" * 60)
    print("RemoteAgent with A2A Protocol - Streaming")
    print("=" * 60)

    agent = RemoteAgent(
        base_url=ADK_SERVER_URL,
        agent_id=AGENT_ID,
        protocol="a2a",
        json_rpc_endpoint="/",
    )

    print("\nStreaming response: ", end="", flush=True)

    # Stream works the same way as local agents
    async for event in agent.arun(
        "Tell me 3 interesting facts about space exploration.",
        stream=True,
    ):
        if isinstance(event, RunContentEvent) and event.content:
            print(event.content, end="", flush=True)

    print("\n")


async def multi_turn_conversation():
    """Multi-turn conversation using session_id (maps to context_id in A2A)."""
    print("\n" + "=" * 60)
    print("RemoteAgent with A2A Protocol - Multi-turn Conversation")
    print("=" * 60)

    agent = RemoteAgent(
        base_url=ADK_SERVER_URL,
        agent_id=AGENT_ID,
        protocol="a2a",
        json_rpc_endpoint="/",
    )

    # First turn - establish context
    print("\n[Turn 1] Setting up context...")
    result1 = await agent.arun("My favorite planet is Saturn. Please remember this.")

    print(f"Session ID: {result1.session_id}")
    print(f"Response: {result1.content[:200]}...")

    # Store session_id for follow-up (this maps to context_id in A2A)
    session_id = result1.session_id

    # Second turn - use same session
    print("\n[Turn 2] Testing context memory...")
    result2 = await agent.arun(
        "What is my favorite planet? Tell me an interesting fact about it.",
        session_id=session_id,  # Continue the conversation
    )

    print(f"Same Session: {result2.session_id == session_id}")
    print(f"Response: {result2.content}")


async def protocol_comparison():
    """Compare the same RemoteAgent interface with different protocols."""
    print("\n" + "=" * 60)
    print("Protocol Comparison - Same Interface, Different Backends")
    print("=" * 60)

    # A2A protocol (Google ADK)
    print("\n--- A2A Protocol (Google ADK) ---")
    a2a_agent = RemoteAgent(
        base_url=ADK_SERVER_URL,
        agent_id=AGENT_ID,
        protocol="a2a",
        json_rpc_endpoint="/",
    )

    result = await a2a_agent.arun("What is the largest planet?")
    print(f"Response: {result.content[:200]}...")

    # Note: To test AgentOS protocol, you'd need an Agno AgentOS server running:
    # agentos_agent = RemoteAgent(
    #     base_url="http://localhost:7003",
    #     agent_id="my-agent",
    #     protocol="agentos",  # default
    # )
    # result = await agentos_agent.arun("What is the largest planet?")

    print("\nBoth protocols use the same RemoteAgent interface!")
    print("Just change protocol='a2a' to connect to A2A servers.")


if __name__ == "__main__":
    asyncio.run(basic_messaging())
    asyncio.run(streaming_response())
    asyncio.run(multi_turn_conversation())
    asyncio.run(protocol_comparison())

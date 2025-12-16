"""Multi-turn conversations with Google ADK A2A Server.

This example demonstrates how to maintain conversation context across
multiple messages using the A2A protocol's context_id feature.

The context_id allows the agent to remember previous interactions and
maintain a coherent conversation flow.

Prerequisites:
    1. Install dependencies:
       pip install agno httpx google-adk uvicorn

    2. Set your Google API key:
       export GOOGLE_API_KEY=your_key

    3. Start Google ADK server:
       python cookbook/agent_os/a2a_client/servers/google_adk_server.py

    4. Run this script:
       python cookbook/agent_os/a2a_client/07_multi_turn_with_google_adk.py

How Context Works:
    1. First message - No context_id provided, server generates one
    2. Subsequent messages - Include context_id from previous response
    3. The agent uses the context to remember previous interactions
"""

import asyncio

from agno.a2a import A2AClient

ADK_SERVER_URL = "http://localhost:8001"
AGENT_ID = "facts_agent"


async def basic_multi_turn():
    """Simple two-turn conversation."""
    print("=" * 60)
    print("Basic Multi-turn Conversation")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        # First message - introduce a topic
        print("\n[Turn 1] Setting up context...")
        result1 = await client.send_message(
            agent_id=AGENT_ID,
            message="My favorite topic is astronomy. Please remember this.",
        )

        print(f"Context ID: {result1.context_id}")
        print(f"Response: {result1.content[:200]}...")

        # Store context_id for follow-up
        context_id = result1.context_id

        # Second message - reference the context
        print("\n[Turn 2] Testing context memory...")
        result2 = await client.send_message(
            agent_id=AGENT_ID,
            message="What is my favorite topic? Tell me an interesting fact about it.",
            context_id=context_id,  # Use same context
        )

        print(f"Same Context ID: {result2.context_id == context_id}")
        print(f"Response: {result2.content}")


async def extended_conversation():
    """Extended multi-turn conversation with topic evolution."""
    print("\n" + "=" * 60)
    print("Extended Conversation")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        context_id = None

        messages = [
            "Tell me about black holes.",
            "How big are they typically?",
            "What's the nearest one to Earth?",
            "Summarize what we discussed.",
        ]

        for i, message in enumerate(messages, 1):
            print(f"\n[Turn {i}] User: {message}")

            result = await client.send_message(
                agent_id=AGENT_ID,
                message=message,
                context_id=context_id,
            )

            # Capture context_id from first response
            if context_id is None:
                context_id = result.context_id
                print(f"  (New context: {context_id[:8]}...)")

            print(f"  Agent: {result.content[:300]}...")
            if len(result.content) > 300:
                print(f"  (... {len(result.content) - 300} more chars)")


async def streaming_multi_turn():
    """Multi-turn conversation with streaming responses.

    NOTE: The basic `to_a2a()` wrapper in Google ADK may not support streaming.
    If streaming fails, use send_message() instead.
    """
    print("\n" + "=" * 60)
    print("Streaming Multi-turn Conversation")
    print("=" * 60)
    print("(NOTE: Google ADK basic to_a2a() may not support streaming)")

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        context_id = None

        # First turn - streaming
        print("\n[Turn 1] Streaming first response...")
        print("Agent: ", end="", flush=True)

        async for event in client.stream_message(
            agent_id=AGENT_ID,
            message="Tell me about Saturn's rings.",
        ):
            if event.is_content and event.content:
                print(event.content, end="", flush=True)

            if event.context_id and not context_id:
                context_id = event.context_id

            if event.is_final:
                print("\n")
                break

        print(f"(Context ID: {context_id[:8] if context_id else 'N/A'}...)")

        # Second turn - streaming with context
        print("\n[Turn 2] Streaming follow-up...")
        print("Agent: ", end="", flush=True)

        async for event in client.stream_message(
            agent_id=AGENT_ID,
            message="How many moons does it have?",
            context_id=context_id,
        ):
            if event.is_content and event.content:
                print(event.content, end="", flush=True)

            if event.is_final:
                print("\n")
                break


async def new_context_vs_existing():
    """Demonstrate the difference between new and existing contexts."""
    print("\n" + "=" * 60)
    print("New Context vs Existing Context")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        # Establish context
        print("\n[Setup] Establishing context...")
        result1 = await client.send_message(
            agent_id=AGENT_ID,
            message="The password is 'OpenSesame'. Remember it for later.",
        )
        original_context = result1.context_id
        print(f"Context established: {original_context[:8]}...")

        # Same context - should remember
        print("\n[Test 1] Same context (should remember)...")
        result2 = await client.send_message(
            agent_id=AGENT_ID,
            message="What was the password I mentioned?",
            context_id=original_context,
        )
        print(f"Response: {result2.content}")

        # New context - should not remember
        print("\n[Test 2] New context (should not remember)...")
        result3 = await client.send_message(
            agent_id=AGENT_ID,
            message="What was the password I mentioned earlier?",
            # No context_id - starts fresh conversation
        )
        print(f"New context: {result3.context_id[:8]}...")
        print(f"Response: {result3.content}")


if __name__ == "__main__":
    asyncio.run(basic_multi_turn())
    asyncio.run(extended_conversation())
    asyncio.run(streaming_multi_turn())
    asyncio.run(new_context_vs_existing())

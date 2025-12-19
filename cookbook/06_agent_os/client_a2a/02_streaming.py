"""
Streaming A2A Messages with A2AClient

This example demonstrates real-time streaming responses
using the A2A protocol.

Prerequisites:
1. Start an AgentOS server with A2A interface:
   python cookbook/clients/a2a/servers/agno_server.py

2. Run this script:
   python cookbook/clients/a2a/02_streaming.py
"""

import asyncio

from agno.a2a import A2AClient


async def basic_streaming():
    """Stream a response from an A2A agent."""
    print("=" * 60)
    print("Streaming A2A Response")
    print("=" * 60)

    client = A2AClient("http://localhost:7003")
    print("\nStreaming response from agent...")
    print("\nResponse: ", end="", flush=True)

    async for event in client.stream_message(
        agent_id="basic-agent",
        message="Tell me a short joke.",
    ):
        # Print content as it arrives
        if event.is_content and event.content:
            print(event.content, end="", flush=True)

        # Check for completion
        if event.is_final:
            print("\n\n[Stream completed]")


async def streaming_with_events():
    """Stream with detailed event tracking."""
    print("\n" + "=" * 60)
    print("Streaming with Event Details")
    print("=" * 60)

    client = A2AClient("http://localhost:7003")
    print("\nEvent log:")

    content_buffer = []

    async for event in client.stream_message(
        agent_id="basic-agent",
        message="What is Python?",
    ):
        # Log event type
        print(f"  [{event.event_type}]", end="")

        if event.content:
            content_buffer.append(event.content)
            # Show preview of content
            preview = event.content[:20] + "..." if len(event.content) > 20 else event.content
            print(f" content: {repr(preview)}")
        else:
            print()

        if event.is_final:
            print("\nFull response:")
            print("".join(content_buffer))


if __name__ == "__main__":
    asyncio.run(basic_streaming())
    asyncio.run(streaming_with_events())

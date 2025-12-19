"""Stream responses from Google ADK A2A Server.

This example demonstrates real-time streaming with the A2A protocol.
Streaming allows you to receive and display the agent's response as it's
being generated, rather than waiting for the complete response.

IMPORTANT: The basic `to_a2a()` wrapper in Google ADK may not support streaming.
If you encounter "Streaming is not supported by the agent" errors, use the
non-streaming `send_message()` method instead (see 05_connect_to_google_adk.py).

Prerequisites:
    1. Install dependencies:
       pip install agno httpx google-adk uvicorn

    2. Set your Google API key:
       export GOOGLE_API_KEY=your_key

    3. Start Google ADK server:
       python cookbook/agent_os/a2a_client/servers/google_adk_server.py

    4. Run this script:
       python cookbook/agent_os/a2a_client/06_streaming_with_google_adk.py

Stream Events:
    - content: Text content being streamed
    - working: Agent is processing
    - completed: Task completed
    - failed: Task failed
"""

import asyncio

from agno.a2a import A2AClient

ADK_SERVER_URL = "http://localhost:8001"
AGENT_ID = "facts_agent"


async def basic_streaming():
    """Stream a response from the Google ADK agent."""
    print("=" * 60)
    print("Streaming from Google ADK Server")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        print("\nStreaming response: ", end="", flush=True)

        event_count = 0
        content_events = 0

        async for event in client.stream_message(
            agent_id=AGENT_ID,
            message="Tell me 3 interesting facts about space exploration.",
        ):
            event_count += 1

            # Print content as it streams
            if event.is_content and event.content:
                print(event.content, end="", flush=True)
                content_events += 1

            # Handle final event
            if event.is_final:
                print("\n")
                break

        print(f"\nTotal events received: {event_count}")
        print(f"Content events: {content_events}")


async def streaming_with_metadata():
    """Stream with event type tracking."""
    print("\n" + "=" * 60)
    print("Streaming with Event Tracking")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        print("\nEvent log:")
        print("-" * 40)

        async for event in client.stream_message(
            agent_id=AGENT_ID,
            message="What's the largest planet in our solar system?",
        ):
            # Log each event type
            if event.is_content:
                content_preview = (event.content or "")[:50]
                if len(event.content or "") > 50:
                    content_preview += "..."
                print(f"  [content] {content_preview}")
            elif event.event_type == "working":
                print(f"  [working] Agent is processing...")
            elif event.event_type == "completed":
                print(f"  [completed] Task finished")
            elif event.is_final:
                print(f"  [final] Stream ended")
                break
            else:
                print(f"  [{event.event_type}] {event.metadata or ''}")


async def collect_full_response():
    """Stream and collect the full response."""
    print("\n" + "=" * 60)
    print("Collect Full Streamed Response")
    print("=" * 60)

    async with A2AClient(ADK_SERVER_URL, json_rpc_endpoint="/") as client:
        print("\nStreaming and collecting...")

        full_response = []
        task_id = None
        context_id = None

        async for event in client.stream_message(
            agent_id=AGENT_ID,
            message="Tell me about the James Webb Space Telescope.",
        ):
            if event.is_content and event.content:
                full_response.append(event.content)

            if event.task_id:
                task_id = event.task_id
            if event.context_id:
                context_id = event.context_id

            if event.is_final:
                break

        complete_text = "".join(full_response)
        print(f"\nTask ID: {task_id}")
        print(f"Context ID: {context_id}")
        print(f"\nFull Response ({len(complete_text)} chars):")
        print("-" * 40)
        print(complete_text)


if __name__ == "__main__":
    asyncio.run(basic_streaming())
    asyncio.run(streaming_with_metadata())
    asyncio.run(collect_full_response())

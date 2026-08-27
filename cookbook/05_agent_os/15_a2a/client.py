"""
Call an A2A Agent with the First-Party Client
=============================================

Use `A2AClient` to send a message, thread a returned `context_id` into a
follow-up, stream another turn, and handle an unavailable server. The client
base URL is the entity root; it appends the message routes itself.

Prerequisites: Start basic.py on port 7779
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/client.py
Try: Observe POST http://127.0.0.1:7779/a2a/agents/a2a-assistant/v1/message:send and http://127.0.0.1:7779/a2a/agents/a2a-assistant/v1/message:stream
"""

import asyncio
import socket

from agno.client.a2a import A2AClient
from agno.exceptions import RemoteServerUnavailableError

# ---------------------------------------------------------------------------
# Create A2A Clients
# ---------------------------------------------------------------------------

AGENT_URL = "http://127.0.0.1:7779/a2a/agents/a2a-assistant"


def create_unavailable_client() -> A2AClient:
    """Reserve and release a local port so the next connection is refused."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        unused_port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{unused_port}/a2a/agents/unavailable"
    return A2AClient(url, timeout=1)


async def run_client() -> None:
    """Exercise send, multi-turn context, streaming, and connection failure."""
    client = A2AClient(AGENT_URL, timeout=60)

    first = await client.send_message(
        "Remember that my project code is cedar-42. Confirm that you stored it."
    )
    if not first.is_completed:
        raise RuntimeError(f"Initial A2A task ended with status {first.status}")

    follow_up = await client.send_message(
        "What project code did I ask you to remember? Reply with only the code.",
        context_id=first.context_id,
    )
    if not follow_up.is_completed:
        raise RuntimeError(f"Follow-up A2A task ended with status {follow_up.status}")
    if follow_up.context_id != first.context_id:
        raise RuntimeError("The server did not preserve the A2A context ID")
    if "cedar-42" not in follow_up.content.lower():
        raise RuntimeError(f"Expected the threaded fact, received: {follow_up.content}")

    print(f"Initial task: {first.task_id}")
    print(f"Context ID: {first.context_id}")
    print(f"Follow-up: {follow_up.content}")
    print("Stream: ", end="", flush=True)

    stream_types: list[str] = []
    saw_content = False
    saw_final = False
    async for event in client.stream_message(
        "Explain in one sentence why context IDs matter.",
        context_id=first.context_id,
    ):
        stream_types.append(event.event_type)
        if event.is_content and event.content:
            saw_content = True
            print(event.content, end="", flush=True)
        if event.is_final:
            saw_final = True

    print()
    if not saw_content or not saw_final:
        raise RuntimeError(f"Incomplete A2A stream event sequence: {stream_types}")
    print(f"Stream events: {', '.join(stream_types)}")

    unavailable_client = create_unavailable_client()
    try:
        await unavailable_client.send_message("Are you available?")
    except RemoteServerUnavailableError as exc:
        print(f"Unavailable server handled: {exc.base_url}")
    else:
        raise RuntimeError("Expected RemoteServerUnavailableError")


# ---------------------------------------------------------------------------
# Run A2A Client
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_client())

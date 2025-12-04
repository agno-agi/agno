"""A2A (Agent-to-Agent) protocol client for Agno.

This module provides a client for communicating with any A2A-compatible
agent server, enabling cross-framework agent communication.

Example:
    ```python
    from agno.a2a import A2AClient

    async with A2AClient("http://localhost:7777") as client:
        result = await client.send_message(
            agent_id="my-agent",
            message="Hello!"
        )
        print(result.content)
    ```

For streaming:
    ```python
    async for event in client.stream_message("agent", "Tell me a story"):
        if event.is_content:
            print(event.content, end="", flush=True)
    ```
"""

from agno.a2a.client import A2AClient
from agno.a2a.exceptions import (
    A2AAgentNotFoundError,
    A2AConnectionError,
    A2AError,
    A2ARequestError,
    A2ATaskFailedError,
    A2ATimeoutError,
)
from agno.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult

__all__ = [
    # Client
    "A2AClient",
    # Schemas
    "AgentCard",
    "Artifact",
    "StreamEvent",
    "TaskResult",
    # Exceptions
    "A2AError",
    "A2AConnectionError",
    "A2AAgentNotFoundError",
    "A2ATaskFailedError",
    "A2ARequestError",
    "A2ATimeoutError",
]


"""A2A (Agent-to-Agent) protocol client for Agno.

This module provides a Pythonic client for communicating with any A2A-compatible
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
"""

import json
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.a2a.exceptions import (
    A2AAgentNotFoundError,
    A2AConnectionError,
    A2AError,
    A2ARequestError,
    A2ATaskFailedError,
    A2ATimeoutError,
)
from agno.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult

try:
    from httpx import AsyncClient, HTTPStatusError, TimeoutException
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


__all__ = ["A2AClient"]


class A2AClient:
    """Async client for A2A (Agent-to-Agent) protocol communication.

    Provides a Pythonic interface for communicating with any A2A-compatible
    agent server, including Agno AgentOS with a2a_interface=True.

    The A2A protocol is a standard for agent-to-agent communication that enables
    interoperability between different AI agent frameworks.

    Attributes:
        base_url: Base URL of the A2A server
        timeout: Request timeout in seconds
        a2a_prefix: URL prefix for A2A endpoints (default: "/a2a")

    Example:
        Basic messaging:
        ```python
        async with A2AClient("http://localhost:7777") as client:
            result = await client.send_message(
                agent_id="my-agent",
                message="What is 2 + 2?"
            )
            print(result.content)
        ```

        Streaming:
        ```python
        async with A2AClient("http://localhost:7777") as client:
            async for event in client.stream_message(
                agent_id="my-agent",
                message="Tell me a story"
            ):
                if event.is_content:
                    print(event.content, end="", flush=True)
        ```

        Multi-turn conversation:
        ```python
        async with A2AClient("http://localhost:7777") as client:
            # First message
            result1 = await client.send_message("agent", "My name is Alice")
            context_id = result1.context_id

            # Continue conversation
            result2 = await client.send_message(
                "agent",
                "What is my name?",
                context_id=context_id
            )
        ```
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 300.0,
        a2a_prefix: str = "/a2a",
    ):
        """Initialize A2AClient.

        Args:
            base_url: Base URL of the A2A server (e.g., "http://localhost:7777")
            timeout: Request timeout in seconds (default: 300)
            a2a_prefix: URL prefix for A2A endpoints (default: "/a2a")
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.a2a_prefix = a2a_prefix
        self._http_client: Optional[AsyncClient] = None

    async def __aenter__(self) -> "A2AClient":
        """Enter async context manager."""
        self._http_client = AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and cleanup resources."""
        await self.close()

    async def connect(self) -> "A2AClient":
        """Explicitly create HTTP client connection.

        Use this when you need to manage the client lifecycle manually
        without using the async context manager.

        Returns:
            A2AClient: self for method chaining
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)
        return self

    async def close(self) -> None:
        """Close HTTP client connections."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _get_endpoint(self, path: str) -> str:
        """Build full endpoint URL."""
        return f"{self.base_url}{self.a2a_prefix}{path}"

    def _build_message_request(
        self,
        agent_id: str,
        message: str,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Build A2A JSON-RPC request payload.

        Args:
            agent_id: Target agent identifier
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier
            images: List of images to include
            files: List of files to include
            metadata: Additional metadata
            stream: Whether this is a streaming request

        Returns:
            Dict containing the JSON-RPC request payload
        """
        message_id = str(uuid4())

        # Build message parts
        parts: List[Dict[str, Any]] = [{"kind": "text", "text": message}]

        # Add images as file parts
        if images:
            for img in images:
                if hasattr(img, "url") and img.url:
                    parts.append(
                        {
                            "kind": "file",
                            "file": {"uri": img.url, "mimeType": "image/*"},
                        }
                    )

        # Add files as file parts
        if files:
            for f in files:
                if hasattr(f, "url") and f.url:
                    mime_type = getattr(f, "mime_type", "application/octet-stream")
                    parts.append(
                        {
                            "kind": "file",
                            "file": {"uri": f.url, "mimeType": mime_type},
                        }
                    )

        # Build metadata
        msg_metadata: Dict[str, Any] = {}
        if user_id:
            msg_metadata["userId"] = user_id
        if metadata:
            msg_metadata.update(metadata)

        # Build the message object, excluding null values
        message_obj: Dict[str, Any] = {
            "messageId": message_id,
            "role": "user",
            "agentId": agent_id,
            "parts": parts,
        }
        if context_id:
            message_obj["contextId"] = context_id
        if msg_metadata:
            message_obj["metadata"] = msg_metadata

        # Build the request
        return {
            "jsonrpc": "2.0",
            "method": "message/stream" if stream else "message/send",
            "id": message_id,
            "params": {
                "message": message_obj
            },
        }

    def _parse_task_result(self, response_data: Dict[str, Any]) -> TaskResult:
        """Parse A2A response into TaskResult.

        Args:
            response_data: Raw JSON-RPC response

        Returns:
            TaskResult with parsed content
        """
        result = response_data.get("result", {})

        # Handle both direct task and nested task formats
        task = result if "id" in result else result.get("task", result)

        # Extract task metadata
        task_id = task.get("id", "")
        context_id = task.get("context_id", task.get("contextId", ""))
        status_obj = task.get("status", {})
        status = status_obj.get("state", "unknown") if isinstance(status_obj, dict) else str(status_obj)

        # Extract content from history
        content_parts: List[str] = []
        for msg in task.get("history", []):
            if msg.get("role") == "agent":
                for part in msg.get("parts", []):
                    part_data = part.get("root", part)  # Handle wrapped parts
                    if part_data.get("kind") == "text" or "text" in part_data:
                        text = part_data.get("text", "")
                        if text:
                            content_parts.append(text)

        # Extract artifacts
        artifacts: List[Artifact] = []
        for artifact_data in task.get("artifacts", []):
            artifacts.append(
                Artifact(
                    artifact_id=artifact_data.get("artifact_id", artifact_data.get("artifactId", "")),
                    name=artifact_data.get("name"),
                    description=artifact_data.get("description"),
                    mime_type=artifact_data.get("mime_type", artifact_data.get("mimeType")),
                    uri=artifact_data.get("uri"),
                )
            )

        return TaskResult(
            task_id=task_id,
            context_id=context_id,
            status=status,
            content="".join(content_parts),
            artifacts=artifacts,
            metadata=task.get("metadata"),
        )

    def _parse_stream_event(self, data: Dict[str, Any]) -> StreamEvent:
        """Parse streaming response line into StreamEvent.

        Args:
            data: Parsed JSON from stream line

        Returns:
            StreamEvent with parsed data
        """
        result = data.get("result", {})

        # Determine event type from various indicators
        event_type = "unknown"
        content = None
        is_final = False
        task_id = result.get("taskId", result.get("task_id"))
        context_id = result.get("contextId", result.get("context_id"))
        metadata = result.get("metadata")

        # Use the 'kind' field to determine event type (A2A protocol standard)
        kind = result.get("kind", "")

        if kind == "task":
            # Final task result
            event_type = "task"
            is_final = True
            task_id = result.get("id", task_id)
            # Extract content from history
            for msg in result.get("history", []):
                if msg.get("role") == "agent":
                    for part in msg.get("parts", []):
                        if part.get("kind") == "text" or "text" in part:
                            content = part.get("text", "")
                            break

        elif kind == "status-update":
            # Status update event
            is_final = result.get("final", False)
            status = result.get("status", {})
            state = status.get("state", "") if isinstance(status, dict) else ""

            if state == "working":
                event_type = "working"
            elif state == "completed":
                event_type = "completed"
            elif state == "failed":
                event_type = "failed"
            elif state == "canceled":
                event_type = "canceled"
            else:
                event_type = "status"

        elif kind == "message":
            # Content message event
            event_type = "content"

            # Check if this is reasoning content
            if metadata and metadata.get("agno_content_category") == "reasoning":
                event_type = "reasoning"

            # Extract text content from parts
            for part in result.get("parts", []):
                if part.get("kind") == "text" or "text" in part:
                    content = part.get("text", "")
                    break

        # Fallback parsing for non-standard formats
        elif "history" in result:
            event_type = "task"
            is_final = True
            task_id = result.get("id", task_id)
            for msg in result.get("history", []):
                if msg.get("role") == "agent":
                    for part in msg.get("parts", []):
                        part_data = part.get("root", part)
                        if "text" in part_data:
                            content = part_data.get("text", "")
                            break

        elif "messageId" in result or "message_id" in result or "parts" in result:
            event_type = "content"
            for part in result.get("parts", []):
                part_data = part.get("root", part)
                if "text" in part_data:
                    content = part_data.get("text", "")
                    break

        return StreamEvent(
            event_type=event_type,
            content=content,
            task_id=task_id,
            context_id=context_id,
            metadata=metadata,
            is_final=is_final,
        )

    async def send_message(
        self,
        agent_id: str,
        message: str,
        *,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """Send a message to an A2A agent and wait for the response.

        Args:
            agent_id: Target agent identifier
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier (optional)
            images: List of images to include (optional)
            files: List of files to include (optional)
            metadata: Additional metadata (optional)

        Returns:
            TaskResult containing the agent's response

        Raises:
            A2AAgentNotFoundError: If the agent is not found
            A2ATaskFailedError: If the task fails
            A2ARequestError: If the request is invalid
            A2AConnectionError: If connection fails
            A2ATimeoutError: If request times out
        """
        if not self._http_client:
            await self.connect()

        request_body = self._build_message_request(
            agent_id=agent_id,
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            files=files,
            metadata=metadata,
            stream=False,
        )

        try:
            response = await self._http_client.post(  # type: ignore
                self._get_endpoint("/message/send"),
                json=request_body,
            )
            response.raise_for_status()
            response_data = response.json()

            # Check for JSON-RPC error
            if "error" in response_data:
                error = response_data["error"]
                raise A2ARequestError(
                    status_code=error.get("code", -1),
                    detail=error.get("message", "Unknown error"),
                )

            result = self._parse_task_result(response_data)

            # Check if task failed
            if result.is_failed:
                raise A2ATaskFailedError(
                    task_id=result.task_id,
                    reason=result.content or "Unknown error",
                )

            return result

        except HTTPStatusError as e:
            if e.response.status_code == 404:
                raise A2AAgentNotFoundError(agent_id) from e
            raise A2ARequestError(
                status_code=e.response.status_code,
                detail=e.response.text,
            ) from e
        except TimeoutException as e:
            raise A2ATimeoutError(f"Request to {agent_id} timed out") from e
        except A2AError:
            raise
        except Exception as e:
            raise A2AConnectionError(f"Failed to connect to A2A server: {e}") from e

    async def stream_message(
        self,
        agent_id: str,
        message: str,
        *,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a message to an A2A agent with real-time events.

        Args:
            agent_id: Target agent identifier
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier (optional)
            images: List of images to include (optional)
            files: List of files to include (optional)
            metadata: Additional metadata (optional)

        Yields:
            StreamEvent objects for each event in the stream

        Raises:
            A2AAgentNotFoundError: If the agent is not found
            A2ARequestError: If the request is invalid
            A2AConnectionError: If connection fails
            A2ATimeoutError: If request times out

        Example:
            ```python
            async for event in client.stream_message("agent", "Hello"):
                if event.is_content and event.content:
                    print(event.content, end="", flush=True)
                elif event.is_final:
                    print()  # Newline at end
            ```
        """
        if not self._http_client:
            await self.connect()

        request_body = self._build_message_request(
            agent_id=agent_id,
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            files=files,
            metadata=metadata,
            stream=True,
        )

        try:
            async with self._http_client.stream(  # type: ignore
                "POST",
                self._get_endpoint("/message/stream"),
                json=request_body,
            ) as response:
                if response.status_code == 404:
                    raise A2AAgentNotFoundError(agent_id)
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        event = self._parse_stream_event(data)
                        yield event

                        # Check for task start to capture IDs
                        if event.event_type == "started":
                            pass  # Could store task_id/context_id if needed

                    except json.JSONDecodeError:
                        # Skip non-JSON lines
                        continue

        except HTTPStatusError as e:
            if e.response.status_code == 404:
                raise A2AAgentNotFoundError(agent_id) from e
            raise A2ARequestError(
                status_code=e.response.status_code,
                detail=str(e),
            ) from e
        except TimeoutException as e:
            raise A2ATimeoutError(f"Stream to {agent_id} timed out") from e
        except A2AError:
            raise
        except Exception as e:
            raise A2AConnectionError(f"Failed to stream from A2A server: {e}") from e

    async def get_agent_card(self, agent_card_path: str = "/.well-known/agent.json") -> Optional[AgentCard]:
        """Get agent card for capability discovery.

        Note: Not all A2A servers support agent cards. This method returns
        None if the server doesn't provide an agent card.

        Args:
            agent_card_path: Path to the agent card endpoint

        Returns:
            AgentCard if available, None otherwise
        """
        if not self._http_client:
            await self.connect()

        try:
            response = await self._http_client.get(  # type: ignore
                f"{self.base_url}{agent_card_path}",
            )
            if response.status_code != 200:
                return None

            data = response.json()
            return AgentCard(
                name=data.get("name", "Unknown"),
                url=data.get("url", self.base_url),
                description=data.get("description"),
                version=data.get("version"),
                capabilities=data.get("capabilities", []),
                metadata=data.get("metadata"),
            )
        except Exception:
            return None


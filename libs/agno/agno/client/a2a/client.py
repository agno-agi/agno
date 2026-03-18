"""A2A (Agent-to-Agent) protocol client for Agno.

This module provides a Pythonic client for communicating with any A2A-compatible
agent server, enabling cross-framework agent communication.

"""

import json
from typing import Any, AsyncIterator, Dict, List, Literal, Optional
from uuid import uuid4

from agno.client.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult
from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, File, Image, Video
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from httpx import ConnectError, ConnectTimeout, TimeoutException
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

    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        protocol: Literal["rest", "json-rpc"] = "rest",
    ):
        """Initialize A2AClient.

        Args:
            base_url: Base URL of the A2A server (e.g., "http://localhost:7777")
            timeout: Request timeout in seconds (default: 30)
            protocol: Protocol to use for A2A communication (default: "rest")
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.protocol = protocol

    def _get_endpoint(self, path: str) -> str:
        """Build full endpoint URL.

        If protocol is "json-rpc", always use the base URL. Otherwise, use the traditional
        REST-style endpoints.
        """
        if self.protocol == "json-rpc":
            return self.base_url if self.base_url.endswith("/") else f"{self.base_url}/"

        # Manually construct URL to ensure proper path joining
        base = self.base_url.rstrip("/")
        path_clean = path.lstrip("/")
        return f"{base}/{path_clean}" if path_clean else base

    def _build_message_request(
        self,
        message: str,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Build A2A JSON-RPC request payload.

        Args:
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier
            images: List of images to include
            audio: List of audio files to include
            videos: List of videos to include
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

        # Add audio as file parts
        if audio:
            for aud in audio:
                if hasattr(aud, "url") and aud.url:
                    parts.append(
                        {
                            "kind": "file",
                            "file": {"uri": aud.url, "mimeType": "audio/*"},
                        }
                    )

        # Add videos as file parts
        if videos:
            for vid in videos:
                if hasattr(vid, "url") and vid.url:
                    parts.append(
                        {
                            "kind": "file",
                            "file": {"uri": vid.url, "mimeType": "video/*"},
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
            "params": {"message": message_obj},
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

            event_type = state if state in {"working", "completed", "failed", "canceled"} else "status"

        elif kind == "message":
            # Content message event
            event_type = "content"

            if metadata and metadata.get("agno_content_category") == "reasoning":
                event_type = "reasoning"

            # Extract text content from parts
            for part in result.get("parts", []):
                if part.get("kind") == "text" or "text" in part:
                    content = part.get("text", "")
                    break
        elif kind == "artifact-update":
            event_type = "content"
            artifact = result.get("artifact", {})
            for part in artifact.get("parts", []):
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
        message: str,
        *,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> TaskResult:
        """Send a message to an A2A agent and wait for the response.

        Args:
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier (optional)
            images: List of Image objects to include (optional)
            audio: List of Audio objects to include (optional)
            videos: List of Video objects to include (optional)
            files: List of File objects to include (optional)
            metadata: Additional metadata (optional)
            headers: HTTP headers to include in the request (optional)
        Returns:
            TaskResult containing the agent's response

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out
        """
        client = get_default_async_client()

        request_body = self._build_message_request(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
            stream=False,
        )
        try:
            response = await client.post(
                self._get_endpoint(path="/v1/message:send"),
                json=request_body,
                timeout=self.timeout,
                headers=headers,
            )
            response.raise_for_status()
            response_data = response.json()

            return self._parse_task_result(response_data)

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

    async def stream_message(
        self,
        message: str,
        *,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a message to an A2A agent with real-time events.

        Args:
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier (optional)
            images: List of Image objects to include (optional)
            audio: List of Audio objects to include (optional)
            videos: List of Video objects to include (optional)
            files: List of File objects to include (optional)
            metadata: Additional metadata (optional)
            headers: HTTP headers to include in the request (optional)
        Yields:
            StreamEvent objects for each event in the stream

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out

        Example:
            ```python
            async for event in client.stream_message("agent", "Hello"):
                if event.is_content and event.content:
                    print(event.content, end="", flush=True)
                elif event.is_final:
                    print()  # Newline at end
            ```
        """
        http_client = get_default_async_client()

        request_body = self._build_message_request(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
            stream=True,
        )

        try:
            if headers is None:
                headers = {}
            if "Accept" not in headers:
                headers["Accept"] = "text/event-stream"
            if "Cache-Control" not in headers:
                headers["Cache-Control"] = "no-store"

            async with http_client.stream(
                "POST",
                self._get_endpoint("/v1/message:stream"),
                json=request_body,
                timeout=self.timeout,
                headers=headers,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    # Handle SSE format: skip "event:" lines, parse "data:" lines
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()  # Remove "data:" prefix

                    try:
                        data = json.loads(line)
                        event = self._parse_stream_event(data)
                        yield event

                        # Check for task start to capture IDs
                        if event.event_type == "started":
                            pass  # Could store task_id/context_id if needed

                    except json.JSONDecodeError as e:
                        log_warning(f"Failed to decode JSON from stream line: {line[:100]}. Error: {e}")
                        continue

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

    def get_agent_card(self, headers: Optional[Dict[str, str]] = None) -> Optional[AgentCard]:
        """Get agent card for capability discovery.

        Note: Not all A2A servers support agent cards. This method returns
        None if the server doesn't provide an agent card.

        Returns:
            AgentCard if available, None otherwise
        """
        client = get_default_sync_client()

        agent_card_path = "/.well-known/agent-card.json"
        url = self._get_endpoint(path=agent_card_path)
        response = client.get(url, timeout=self.timeout, headers=headers)
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

    async def aget_agent_card(self, headers: Optional[Dict[str, str]] = None) -> Optional[AgentCard]:
        """Get agent card for capability discovery.

        Note: Not all A2A servers support agent cards. This method returns
        None if the server doesn't provide an agent card.

        Returns:
            AgentCard if available, None otherwise
        """
        client = get_default_async_client()

        agent_card_path = "/.well-known/agent-card.json"
        url = self._get_endpoint(path=agent_card_path)
        response = await client.get(url, timeout=self.timeout, headers=headers)
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

"""A2A (Agent-to-Agent) protocol client for Agno.

This module provides a Pythonic client for communicating with any A2A-compatible
agent server, enabling cross-framework agent communication.

"""

import json
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Set
from uuid import uuid4

from agno.client.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult
from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, File, Image, Video
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from httpx import AsyncClient, ConnectError, ConnectTimeout, HTTPStatusError, RequestError, TimeoutException
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")

try:
    from a2a.client import A2AClientError, A2AClientTimeoutError, ClientConfig, ClientFactory
    from a2a.client.card_resolver import parse_agent_card
    from a2a.helpers import get_data_parts, get_text_parts, new_data_part
    from a2a.types import (
        AgentCapabilities,
        AgentInterface,
        CancelTaskRequest,
        GetTaskRequest,
        Part,
        Role,
        SendMessageRequest,
        StreamResponse,
        Task,
        TaskState,
    )
    from a2a.types import AgentCard as A2AAgentCard
    from a2a.types import Message as A2AMessage
    from google.protobuf.json_format import MessageToDict
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


__all__ = ["A2AClient"]

_AGENT_CARD_PATH = "/.well-known/agent-card.json"
_TASK_STATES = {
    TaskState.TASK_STATE_SUBMITTED: "submitted",
    TaskState.TASK_STATE_WORKING: "working",
    TaskState.TASK_STATE_COMPLETED: "completed",
    TaskState.TASK_STATE_FAILED: "failed",
    TaskState.TASK_STATE_CANCELED: "canceled",
    TaskState.TASK_STATE_INPUT_REQUIRED: "input-required",
    TaskState.TASK_STATE_REJECTED: "rejected",
    TaskState.TASK_STATE_AUTH_REQUIRED: "auth-required",
}
_FINAL_TASK_STATES = ("completed", "failed", "canceled", "rejected", "input-required", "auth-required")


class A2AClient:
    """Async client for A2A (Agent-to-Agent) protocol communication.

    Provides a Pythonic interface for communicating with any A2A-compatible
    agent server, including Agno AgentOS with a2a_interface=True.

    The A2A protocol is a standard for agent-to-agent communication that enables
    interoperability between different AI agent frameworks. The client reads the
    server's Agent Card and speaks the protocol version the server supports
    (A2A v1.0, or v0.3 for older servers).

    Attributes:
        base_url: Base URL of the A2A agent
        timeout: Request timeout in seconds
        protocol: Deprecated. The protocol is negotiated from the Agent Card.

    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        protocol: Literal["rest", "json-rpc"] = "rest",
    ):
        """Initialize A2AClient.

        Args:
            base_url: URL of the agent's A2A endpoint (e.g., "http://localhost:7777/a2a/agents/my-agent")
            timeout: Request timeout in seconds (default: 30)
            protocol: Deprecated. The protocol is negotiated from the Agent Card.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.protocol = protocol
        if protocol != "rest":
            log_warning(
                "The `protocol` argument of A2AClient is deprecated and will be removed in a future release. "
                "The protocol is negotiated from the Agent Card instead."
            )

        self._agent_card: Optional[A2AAgentCard] = None

    def _get_endpoint(self, path: str) -> str:
        """Build full endpoint URL."""
        # Manually construct URL to ensure proper path joining
        base = self.base_url.rstrip("/")
        path_clean = path.lstrip("/")
        return f"{base}/{path_clean}" if path_clean else base

    def _restore_integers(self, value: Any) -> Any:
        """Restore the integers of data read from an A2A response.

        A2A carries structured data as JSON numbers, which are read back as floats.

        Args:
            value: The data read from the A2A response

        Returns:
            The data with whole numbers turned back into integers
        """
        if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
            return int(value)
        if isinstance(value, dict):
            return {key: self._restore_integers(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._restore_integers(item) for item in value]
        return value

    def _get_data(self, parts: Any) -> Optional[Any]:
        """Get the structured data of the first data part, if any.

        Args:
            parts: The parts of an A2A message or artifact

        Returns:
            The structured data, or None when no part carries data
        """
        data_parts = get_data_parts(parts)
        return self._restore_integers(data_parts[0]) if data_parts else None

    def _get_metadata(self, metadata: Any) -> Optional[Dict[str, Any]]:
        """Get A2A metadata as a dict.

        Args:
            metadata: The metadata of an A2A message, task or event

        Returns:
            The metadata as a dict, or None when there is none
        """
        return self._restore_integers(MessageToDict(metadata)) or None

    def _build_message(
        self,
        message: str,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> A2AMessage:
        """Build the A2A message to send.

        Args:
            message: Text message to send
            context_id: Session/context ID for multi-turn conversations
            user_id: User identifier
            images: List of images to include
            audio: List of audio files to include
            videos: List of videos to include
            files: List of files to include
            metadata: Additional metadata
            task_id: ID of the task the message continues
            data: Structured data to include

        Returns:
            The A2A Message
        """
        # Build message parts
        parts: List[Part] = [Part(text=message)] if message else []

        # Add structured data as a data part
        if data is not None:
            parts.append(new_data_part(data, media_type="application/json"))

        # Add images as file parts
        if images:
            for img in images:
                if hasattr(img, "url") and img.url:
                    parts.append(Part(url=img.url, media_type=getattr(img, "mime_type", None) or "image/*"))
                elif isinstance(getattr(img, "content", None), bytes):
                    parts.append(Part(raw=img.content, media_type=getattr(img, "mime_type", None) or "image/*"))

        # Add audio as file parts
        if audio:
            for aud in audio:
                if hasattr(aud, "url") and aud.url:
                    parts.append(Part(url=aud.url, media_type=getattr(aud, "mime_type", None) or "audio/*"))
                elif isinstance(getattr(aud, "content", None), bytes):
                    parts.append(Part(raw=aud.content, media_type=getattr(aud, "mime_type", None) or "audio/*"))

        # Add videos as file parts
        if videos:
            for vid in videos:
                if hasattr(vid, "url") and vid.url:
                    parts.append(Part(url=vid.url, media_type=getattr(vid, "mime_type", None) or "video/*"))
                elif isinstance(getattr(vid, "content", None), bytes):
                    parts.append(Part(raw=vid.content, media_type=getattr(vid, "mime_type", None) or "video/*"))

        # Add files as file parts
        if files:
            for f in files:
                mime_type = getattr(f, "mime_type", None) or "application/octet-stream"
                if hasattr(f, "url") and f.url:
                    parts.append(Part(url=f.url, media_type=mime_type))
                elif isinstance(getattr(f, "content", None), bytes):
                    parts.append(Part(raw=f.content, media_type=mime_type))

        # Build metadata
        msg_metadata: Dict[str, Any] = {}
        if user_id:
            msg_metadata["userId"] = user_id
        if metadata:
            msg_metadata.update(metadata)

        # Build the message object
        a2a_message = A2AMessage(message_id=str(uuid4()), role=Role.ROLE_USER, parts=parts)
        if context_id:
            a2a_message.context_id = context_id
        if task_id:
            a2a_message.task_id = task_id
        if msg_metadata:
            a2a_message.metadata.update(msg_metadata)
        return a2a_message

    def _parse_artifacts(self, task: Task) -> List[Artifact]:
        """Parse the file artifacts (images, audio, ...) of an A2A task.

        Args:
            task: The A2A task

        Returns:
            The artifacts of the task that carry a file
        """
        artifacts: List[Artifact] = []
        for artifact in task.artifacts:
            for part in artifact.parts:
                if not part.HasField("url") and not part.HasField("raw"):
                    continue
                artifacts.append(
                    Artifact(
                        artifact_id=artifact.artifact_id,
                        name=artifact.name or None,
                        description=artifact.description or None,
                        mime_type=part.media_type or None,
                        uri=part.url if part.HasField("url") else None,
                        content=part.raw if part.HasField("raw") else None,
                    )
                )
        return artifacts

    def _parse_task_result(self, response: StreamResponse) -> TaskResult:
        """Parse A2A response into TaskResult.

        Args:
            response: The A2A response, holding either a task or a single message

        Returns:
            TaskResult with parsed content
        """
        # A server can answer with a single message instead of a task
        if response.HasField("message"):
            message = response.message
            data = self._get_data(message.parts)
            content = "".join(get_text_parts(message.parts))
            return TaskResult(
                task_id=message.task_id,
                context_id=message.context_id,
                status="completed",
                content=content if content or data is None else json.dumps(data),
                metadata=self._get_metadata(message.metadata),
                data=data,
            )

        task = response.task
        status = _TASK_STATES.get(task.status.state, "unknown")

        # The response lives in the task artifacts. Reasoning is kept out of it.
        content = ""
        data = None
        for artifact in task.artifacts:
            if dict(artifact.metadata).get("agno_content_category") == "reasoning":
                continue
            content += "".join(get_text_parts(artifact.parts))
            if data is None:
                data = self._get_data(artifact.parts)

        # Fall back to the status message (errors, input requests), then to the agent messages in the history
        if task.status.HasField("message"):
            if not content:
                content = "".join(get_text_parts(task.status.message.parts))
            if data is None:
                data = self._get_data(task.status.message.parts)
        if not content:
            for msg in task.history:
                if msg.role == Role.ROLE_AGENT:
                    content += "".join(get_text_parts(msg.parts))

        # Structured content with no text is also given as its JSON string
        if not content and data is not None:
            content = json.dumps(data)

        return TaskResult(
            task_id=task.id,
            context_id=task.context_id,
            status=status,
            content=content,
            artifacts=self._parse_artifacts(task),
            metadata=self._get_metadata(task.metadata),
            data=data,
        )

    def _parse_stream_event(self, response: StreamResponse) -> StreamEvent:
        """Parse streaming response into StreamEvent.

        Args:
            response: The A2A streaming response

        Returns:
            StreamEvent with parsed data
        """
        event_type = "unknown"
        content = None
        data = None
        task_id = None
        context_id = None
        metadata = None
        is_final = False
        status = None

        # Determine event type from the payload the response holds
        payload = response.WhichOneof("payload")

        if payload == "task":
            task_result = self._parse_task_result(response)
            event_type = "task"
            task_id = task_result.task_id
            context_id = task_result.context_id
            content = task_result.content or None
            data = task_result.data
            metadata = task_result.metadata
            status = task_result.status
            is_final = status in _FINAL_TASK_STATES

        elif payload == "status_update":
            status_update = response.status_update
            task_id = status_update.task_id
            context_id = status_update.context_id
            metadata = self._get_metadata(status_update.metadata)
            status = _TASK_STATES.get(status_update.status.state, "unknown")
            is_final = status in _FINAL_TASK_STATES

            # Tool calls ride working status updates, named in the metadata
            agno_event_type = (metadata or {}).get("agno_event_type")
            if status == "working" and agno_event_type in ("tool_call_started", "tool_call_completed"):
                event_type = agno_event_type
            else:
                event_type = status if status in {"working", "completed", "failed", "canceled"} else "status"
            if status_update.status.HasField("message"):
                content = "".join(get_text_parts(status_update.status.message.parts)) or None
                data = self._get_data(status_update.status.message.parts)

        elif payload == "artifact_update":
            artifact_update = response.artifact_update
            task_id = artifact_update.task_id
            context_id = artifact_update.context_id
            metadata = self._get_metadata(artifact_update.artifact.metadata)
            event_type = "content"
            if metadata and metadata.get("agno_content_category") == "reasoning":
                event_type = "reasoning"
            content = "".join(get_text_parts(artifact_update.artifact.parts)) or None
            data = self._get_data(artifact_update.artifact.parts)

        elif payload == "message":
            # A single message is the whole response: there is no task to follow
            message = response.message
            task_id = message.task_id or None
            context_id = message.context_id or None
            metadata = self._get_metadata(message.metadata)
            event_type = "content"
            if metadata and metadata.get("agno_content_category") == "reasoning":
                event_type = "reasoning"
            content = "".join(get_text_parts(message.parts)) or None
            data = self._get_data(message.parts)
            status = "completed"
            is_final = True

        return StreamEvent(
            event_type=event_type,
            content=content,
            task_id=task_id,
            context_id=context_id,
            metadata=metadata,
            is_final=is_final,
            data=data,
            status=status,
        )

    def _map_agent_card(self, a2a_card: A2AAgentCard) -> AgentCard:
        """Map the A2A protocol Agent Card to Agno's AgentCard.

        Args:
            a2a_card: The Agent Card as the A2A server serves it

        Returns:
            AgentCard with the agent's name, endpoint, capabilities and skills
        """
        card_data = MessageToDict(a2a_card)
        interfaces = card_data.get("supportedInterfaces", [])
        return AgentCard(
            name=a2a_card.name or "Unknown",
            url=interfaces[0].get("url", self.base_url) if interfaces else self.base_url,
            description=a2a_card.description or None,
            version=a2a_card.version or None,
            capabilities=card_data.get("capabilities", {}),
            metadata=card_data.get("metadata"),
            interfaces=interfaces,
            skills=card_data.get("skills", []),
            security_schemes=card_data.get("securitySchemes", {}),
        )

    def _use_base_url(self, a2a_card: A2AAgentCard) -> A2AAgentCard:
        """Point the card's interfaces at the base URL.

        The host a card advertises can be unreachable from here (a container hostname, a
        server behind a proxy), so requests go to the base URL the caller was given.
        """
        for interface in a2a_card.supported_interfaces:
            interface.url = self.base_url
        return a2a_card

    async def _aget_a2a_card(self, headers: Optional[Dict[str, str]] = None) -> A2AAgentCard:
        """Get the Agent Card the protocol is negotiated from, fetching it on first use.

        A server without an Agent Card is assumed to serve A2A v1.0 over JSON-RPC on the base URL.

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            The Agent Card of the A2A server
        """
        if self._agent_card is not None:
            return self._agent_card

        client = get_default_async_client()
        response = await client.get(self._get_endpoint(path=_AGENT_CARD_PATH), timeout=self.timeout, headers=headers)
        if response.status_code == 200:
            self._agent_card = self._use_base_url(parse_agent_card(response.json()))
            return self._agent_card

        # Not kept: the card is fetched again on the next call, in case it was only unavailable
        return A2AAgentCard(
            supported_interfaces=[
                AgentInterface(url=self.base_url, protocol_binding="JSONRPC", protocol_version="1.0")
            ],
            capabilities=AgentCapabilities(streaming=True),
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
        task_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
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
            task_id: ID of a task waiting for input, to continue it (optional)
            data: Structured data to send, e.g. the resolved requirements of a paused task (optional)
        Returns:
            TaskResult containing the agent's response

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out
        """
        a2a_message = self._build_message(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
            task_id=task_id,
            data=data,
        )
        try:
            agent_card = await self._aget_a2a_card(headers=headers)

            # The A2A client owns and closes the http client it is given, so it gets its own
            async with AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as http_client:
                client = ClientFactory(ClientConfig(httpx_client=http_client, streaming=False)).create(agent_card)
                async for response in client.send_message(SendMessageRequest(message=a2a_message)):
                    return self._parse_task_result(response)

            raise A2AClientError("The A2A server returned no response")

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except (TimeoutException, A2AClientTimeoutError) as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except A2AClientError as e:
            # The A2A client wraps http errors, re-raise the original
            if isinstance(e.__cause__, HTTPStatusError):
                raise e.__cause__
            if isinstance(e.__cause__, RequestError):
                raise RemoteServerUnavailableError(
                    message=f"Failed to connect to A2A server at {self.base_url}",
                    base_url=self.base_url,
                    original_error=e.__cause__,
                ) from e
            raise

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
        task_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
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
            task_id: ID of a task waiting for input, to continue it (optional)
            data: Structured data to send, e.g. the resolved requirements of a paused task (optional)
        Yields:
            StreamEvent objects for each event in the stream

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out

        Example:
            ```python
            async for event in client.stream_message("Hello"):
                if event.is_content and event.content:
                    print(event.content, end="", flush=True)
                elif event.is_final:
                    print()  # Newline at end
            ```
        """
        a2a_message = self._build_message(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
            task_id=task_id,
            data=data,
        )
        # Artifacts already streamed chunk by chunk, by artifact id
        streamed_artifact_ids: Set[str] = set()

        try:
            agent_card = await self._aget_a2a_card(headers=headers)

            # The A2A client owns and closes the http client it is given, so it gets its own
            async with AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as http_client:
                client = ClientFactory(ClientConfig(httpx_client=http_client, streaming=True)).create(agent_card)
                async for response in client.send_message(SendMessageRequest(message=a2a_message)):
                    event = self._parse_stream_event(response)

                    # A server closes a streamed artifact by sending it again in full. Deliver that
                    # as an "artifact" event, so the chunks already delivered are not repeated as content.
                    if response.HasField("artifact_update"):
                        artifact_update = response.artifact_update
                        artifact_id = artifact_update.artifact.artifact_id
                        if artifact_update.append:
                            streamed_artifact_ids.add(artifact_id)
                        elif artifact_update.last_chunk and artifact_id in streamed_artifact_ids:
                            event.event_type = "artifact"
                        elif not artifact_update.last_chunk:
                            streamed_artifact_ids.add(artifact_id)

                    yield event

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except (TimeoutException, A2AClientTimeoutError) as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except A2AClientError as e:
            # The A2A client wraps http errors, re-raise the original
            if isinstance(e.__cause__, HTTPStatusError):
                raise e.__cause__
            if isinstance(e.__cause__, RequestError):
                raise RemoteServerUnavailableError(
                    message=f"Failed to connect to A2A server at {self.base_url}",
                    base_url=self.base_url,
                    original_error=e.__cause__,
                ) from e
            raise

    async def get_task(self, task_id: str, *, headers: Optional[Dict[str, str]] = None) -> TaskResult:
        """Get the current state of a task, e.g. to follow a run the server is still working on.

        Args:
            task_id: Task identifier, as returned by send_message() or a stream event
            headers: HTTP headers to include in the request (optional)

        Returns:
            TaskResult containing the task's current status and response

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out
        """
        try:
            agent_card = await self._aget_a2a_card(headers=headers)

            # The A2A client owns and closes the http client it is given, so it gets its own
            async with AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as http_client:
                client = ClientFactory(ClientConfig(httpx_client=http_client, streaming=False)).create(agent_card)
                task = await client.get_task(GetTaskRequest(id=task_id))
                return self._parse_task_result(StreamResponse(task=task))

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except (TimeoutException, A2AClientTimeoutError) as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except A2AClientError as e:
            # The A2A client wraps http errors, re-raise the original
            if isinstance(e.__cause__, HTTPStatusError):
                raise e.__cause__
            if isinstance(e.__cause__, RequestError):
                raise RemoteServerUnavailableError(
                    message=f"Failed to connect to A2A server at {self.base_url}",
                    base_url=self.base_url,
                    original_error=e.__cause__,
                ) from e
            raise

    async def cancel_task(self, task_id: str, *, headers: Optional[Dict[str, str]] = None) -> TaskResult:
        """Cancel a task the server is still working on.

        Args:
            task_id: Task identifier, as returned by send_message() or a stream event
            headers: HTTP headers to include in the request (optional)

        Returns:
            TaskResult containing the task's status after the cancellation

        Raises:
            HTTPStatusError: If the server returns an HTTP error (4xx, 5xx)
            RemoteServerUnavailableError: If connection fails or times out
        """
        try:
            agent_card = await self._aget_a2a_card(headers=headers)

            # The A2A client owns and closes the http client it is given, so it gets its own
            async with AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as http_client:
                client = ClientFactory(ClientConfig(httpx_client=http_client, streaming=False)).create(agent_card)
                task = await client.cancel_task(CancelTaskRequest(id=task_id))
                return self._parse_task_result(StreamResponse(task=task))

        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except (TimeoutException, A2AClientTimeoutError) as e:
            raise RemoteServerUnavailableError(
                message=f"Request to A2A server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except A2AClientError as e:
            # The A2A client wraps http errors, re-raise the original
            if isinstance(e.__cause__, HTTPStatusError):
                raise e.__cause__
            if isinstance(e.__cause__, RequestError):
                raise RemoteServerUnavailableError(
                    message=f"Failed to connect to A2A server at {self.base_url}",
                    base_url=self.base_url,
                    original_error=e.__cause__,
                ) from e
            raise

    def get_agent_card(self, headers: Optional[Dict[str, str]] = None) -> Optional[AgentCard]:
        """Get agent card for capability discovery.

        Note: Not all A2A servers support agent cards. This method returns
        None if the server doesn't provide an agent card.

        Returns:
            AgentCard if available, None otherwise
        """
        client = get_default_sync_client()

        url = self._get_endpoint(path=_AGENT_CARD_PATH)
        response = client.get(url, timeout=self.timeout, headers=headers)
        if response.status_code != 200:
            return None

        a2a_card = parse_agent_card(response.json())
        agent_card = self._map_agent_card(a2a_card)
        self._agent_card = self._use_base_url(a2a_card)
        return agent_card

    async def aget_agent_card(self, headers: Optional[Dict[str, str]] = None) -> Optional[AgentCard]:
        """Get agent card for capability discovery.

        Note: Not all A2A servers support agent cards. This method returns
        None if the server doesn't provide an agent card.

        Returns:
            AgentCard if available, None otherwise
        """
        client = get_default_async_client()

        url = self._get_endpoint(path=_AGENT_CARD_PATH)
        response = await client.get(url, timeout=self.timeout, headers=headers)
        if response.status_code != 200:
            return None

        a2a_card = parse_agent_card(response.json())
        agent_card = self._map_agent_card(a2a_card)
        self._agent_card = self._use_base_url(a2a_card)
        return agent_card

"""A2A (Agent-to-Agent) protocol client for Agno.

This module provides a Pythonic client for communicating with any A2A-compatible
agent server, enabling cross-framework agent communication.

"""

from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Union
from uuid import uuid4

from a2a.client import Client, ClientCallContext, ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard as SDKAgentCard
from a2a.types import (
    Artifact as SDKArtifact,
)
from a2a.types import (
    DataPart,
    FilePart,
    FileWithUri,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
    TransportProtocol,
)

from agno.client.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult
from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, File, Image, Video
from agno.utils.http import get_default_async_client, get_default_sync_client

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
        self._sdk_client: Optional[Client] = None

    async def _get_sdk_client(self) -> Client:
        """Get or create the underlying SDK client."""
        if self._sdk_client:
            return self._sdk_client

        transport_protocol = (
            TransportProtocol.jsonrpc
            if self.protocol == "json-rpc"
            else TransportProtocol.http_json
        )

        config = ClientConfig(
            httpx_client=get_default_async_client(),
            supported_transports=[transport_protocol],
        )

        try:
            # Connect using ClientFactory which handles card resolution
            self._sdk_client = await ClientFactory.connect(
                self.base_url,
                client_config=config,
            )
        except Exception as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to A2A server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e

        return self._sdk_client

    def _convert_artifact(self, sdk_artifact: SDKArtifact) -> Artifact:
        """Convert SDK Artifact to Agno Artifact."""
        uri = None
        mime_type = None
        content = None

        # Extract data from parts
        if sdk_artifact.parts:
            for part in sdk_artifact.parts:
                if isinstance(part, FilePart):
                    if isinstance(part.file, FileWithUri):
                        uri = part.file.uri
                        mime_type = part.file.mime_type
                    # Handle FileWithBytes if needed
                elif isinstance(part, DataPart):
                    if isinstance(part.data, bytes):
                        content = part.data
                        mime_type = part.metadata.get("mime_type") if part.metadata else None

        return Artifact(
            artifact_id=sdk_artifact.artifact_id,
            name=sdk_artifact.name,
            description=sdk_artifact.description,
            mime_type=mime_type,
            uri=uri,
            content=content,
        )

    def _convert_task_to_result(self, task: Task) -> TaskResult:
        """Convert SDK Task to Agno TaskResult."""
        content_parts = []
        if task.history:
            for msg in task.history:
                if msg.role == "agent" and msg.parts:
                    for part in msg.parts:
                        p = part.root if hasattr(part, "root") else part
                        if isinstance(p, TextPart):
                            content_parts.append(p.text)

        artifacts = [self._convert_artifact(a) for a in task.artifacts] if task.artifacts else []

        status_state = str(getattr(task.status.state, "value", task.status.state)) if task.status else "unknown"

        return TaskResult(
            task_id=task.id,
            context_id=task.context_id or "",
            status=status_state,
            content="".join(content_parts),
            artifacts=artifacts,
            metadata=task.metadata,
        )
    
    def _convert_agent_card(self, sdk_card: SDKAgentCard) -> AgentCard:
        """Convert SDK AgentCard to Agno AgentCard."""
        return AgentCard(
            name=sdk_card.name,
            url=sdk_card.url or self.base_url,
            description=sdk_card.description,
            version=sdk_card.version,
            capabilities=[cap for cap in dir(sdk_card.capabilities) if not cap.startswith("_")] if sdk_card.capabilities else [],
            metadata=None,
        )

    def _convert_message_parts(
        self,
        message: str,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
    ) -> List[Part]:
        """Convert inputs to SDK Message parts."""
        parts: List[Part] = [
            Part(root=TextPart(text=message))
        ]

        if images:
            for img in images:
                if hasattr(img, "url") and img.url:
                    parts.append(
                        Part(root=FilePart(
                            file=FileWithUri(uri=img.url, mime_type="image/*")
                        ))
                    )

        if audio:
            for aud in audio:
                if hasattr(aud, "url") and aud.url:
                    parts.append(
                        Part(root=FilePart(
                            file=FileWithUri(uri=aud.url, mime_type="audio/*")
                        ))
                    )

        if videos:
            for vid in videos:
                if hasattr(vid, "url") and vid.url:
                    parts.append(
                        Part(root=FilePart(
                            file=FileWithUri(uri=vid.url, mime_type="video/*")
                        ))
                    )

        if files:
            for f in files:
                if hasattr(f, "url") and f.url:
                    mime = getattr(f, "mime_type", "application/octet-stream")
                    parts.append(
                        Part(root=FilePart(
                            file=FileWithUri(uri=f.url, mime_type=mime)
                        ))
                    )

        return parts

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
        client = await self._get_sdk_client()

        parts = self._convert_message_parts(message, images, audio, videos, files)
        
        req_metadata = metadata or {}
        if user_id:
            req_metadata["userId"] = user_id

        msg_obj = Message(
            role=Role.user,
            message_id=str(uuid4()),
            parts=parts,
            context_id=context_id,
            metadata=req_metadata,
        )

        context = None
        if headers:
            context = ClientCallContext(state={"http_kwargs": {"headers": headers}})

        try:
            final_task: Optional[Task] = None
            
            async for item in client.send_message(
                msg_obj, 
                context=context
            ):
                if isinstance(item, tuple):
                    task, event = item
                    final_task = task
                elif isinstance(item, Message):
                    pass
                elif isinstance(item, Task):
                    final_task = item
            
            if final_task:
                return self._convert_task_to_result(final_task)
            
            raise RemoteServerUnavailableError(
                message="No task result received from A2A server",
                base_url=self.base_url
            )

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
        except Exception as e:
             raise RemoteServerUnavailableError(
                message=f"A2A Client Error: {str(e)}",
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
        """
        client = await self._get_sdk_client()
        parts = self._convert_message_parts(message, images, audio, videos, files)
        
        req_metadata = metadata or {}
        if user_id:
            req_metadata["userId"] = user_id

        msg_obj = Message(
            role=Role.user,
            message_id=str(uuid4()),
            parts=parts,
            context_id=context_id,
            metadata=req_metadata,
        )

        context = None
        if headers:
            context = ClientCallContext(state={"http_kwargs": {"headers": headers}})

        last_content_len = 0

        try:
            async for item in client.send_message(msg_obj, context=context):
                if isinstance(item, tuple):
                    task, event = item
                    
                    # 1. Handle content streaming from Task history
                    current_content = ""
                    if task.history:
                         agent_msgs = [m for m in task.history if m.role == "agent"]
                         if agent_msgs:
                             last_msg = agent_msgs[-1]
                             texts = []
                             for p in last_msg.parts:
                                 real_p = p.root if hasattr(p, "root") else p
                                 if isinstance(real_p, TextPart):
                                     texts.append(real_p.text)
                             current_content = "".join(texts)
                    
                    if len(current_content) > last_content_len:
                        delta = current_content[last_content_len:]
                        yield StreamEvent(
                            event_type="content",
                            content=delta,
                            task_id=task.id,
                            context_id=task.context_id,
                            metadata=event.metadata if event else None,
                        )
                        last_content_len = len(current_content)

                    # 2. Handle events
                    if event:
                        event_type = "unknown"
                        is_final = False
                        
                        if isinstance(event, TaskStatusUpdateEvent):
                            status_state = (
                                str(getattr(event.status.state, "value", event.status.state))
                                if event.status
                                else "unknown"
                            )
                            if status_state in {"working", "completed", "failed", "canceled"}:
                                event_type = status_state
                            else:
                                event_type = "status"
                            
                            is_final = event.final
                            
                            if is_final:
                                yield StreamEvent(
                                    event_type=event_type,
                                    task_id=task.id,
                                    context_id=task.context_id,
                                    metadata=event.metadata,
                                    is_final=True,
                                )

        except Exception as e:
             raise RemoteServerUnavailableError(
                message=f"A2A Client Error: {str(e)}",
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
        
        base = self.base_url.rstrip("/")
        url = f"{base}{agent_card_path}"

        try:
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
        except Exception:
            return None

    async def aget_agent_card(self, headers: Optional[Dict[str, str]] = None) -> Optional[AgentCard]:
        """Get agent card for capability discovery (async).

        Returns:
            AgentCard if available, None otherwise
        """
        client = get_default_async_client()
        resolver = A2ACardResolver(
            httpx_client=client,
            base_url=self.base_url
        )
        try:
           sdk_card = await resolver.get_agent_card(http_kwargs={"headers": headers})
           return self._convert_agent_card(sdk_card)
        except Exception:
           return None

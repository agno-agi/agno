"""A2A (Agent-to-Agent) protocol client for Agno.

This module wraps the official `a2a-sdk` client so Agno users get the
benefits of an actively maintained protocol implementation while keeping
the same Pythonic ``A2AClient``, ``TaskResult``, ``StreamEvent`` and
``Artifact`` API. See https://github.com/a2aproject/a2a-python for the
underlying SDK and https://docs.agno.com/agent-os/interfaces/a2a for
the Agno integration context.
"""

import uuid
import warnings
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from agno.client.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult
from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, File, Image, Video

try:
    from a2a.client import (
        A2ACardResolver,
        Client,
        ClientConfig,
        ClientFactory,
    )
    from a2a.types import (
        AgentCard as SDKAgentCard,
        FilePart,
        FileWithUri,
        Message as A2AMessage,
        Part,
        Role,
        Task,
        TaskState,
        TextPart,
    )
except ImportError as e:
    raise ImportError(
        '`a2a-sdk` not installed. Please install with `pip install "a2a-sdk>=0.3.0,<0.4"` '
        "to use the A2A client. (The Agno server-side A2A router also depends on a2a-sdk.)"
    ) from e

try:
    from httpx import AsyncClient
except ImportError as e:  # pragma: no cover - httpx is a hard agno dep
    raise ImportError("`httpx` not installed. Install with `pip install httpx`.") from e


__all__ = ["A2AClient"]


# Default A2A well-known path used by both Agno's A2A router and the
# official A2ACardResolver. Kept here so sync ``get_agent_card`` can build the
# same URL without instantiating a resolver.
_AGENT_CARD_WELL_KNOWN_PATH = "/.well-known/agent-card.json"


class A2AClient:
    """Async client for A2A (Agent-to-Agent) protocol communication.

    Wraps `a2a-sdk` so the same protocol implementation drives every Agno
    A2A consumer, and the upstream SDK is responsible for tracking the
    evolving JSON-RPC and HTTP+JSON bindings the A2A working group
    publishes.

    Attributes:
        base_url: Base URL of the A2A server
        timeout: Request timeout in seconds

    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        protocol: Literal["rest", "json-rpc"] = "json-rpc",
    ):
        """Initialize A2AClient.

        Args:
            base_url: Base URL of the A2A server
                (e.g. ``"http://localhost:7003/a2a/agents/basic-agent"``).
            timeout: Request timeout in seconds (default: 30).
            protocol: Kept for backwards compatibility. ``a2a-sdk`` ships a
                JSON-RPC transport by default, which is what Agno's A2A
                router implements. ``"json-rpc"`` is the default. The
                legacy ``"rest"`` value is accepted and ignored (with a
                deprecation warning) so existing Agno callers do not break.
        """
        if protocol not in ("rest", "json-rpc"):
            raise ValueError(f"Unsupported protocol: {protocol!r}")
        if protocol == "rest":
            warnings.warn(
                "A2AClient(protocol='rest') is deprecated; the a2a-sdk "
                "transports are used directly and only JSON-RPC is supported "
                "by the Agno A2A router. Pass protocol='json-rpc' to silence.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.protocol = protocol
        # The SDK client is created lazily on first use so that constructing
        # an A2AClient is cheap and never requires the SDK transports to be
        # ready (this matters for tests that mock out the call site).
        self._sdk_client: Optional[Client] = None
        self._http_client: Optional[AsyncClient] = None
        self._cached_card: Optional[SDKAgentCard] = None

    async def _ensure_sdk_client(self) -> Client:
        """Create the underlying a2a-sdk client (and resolve the AgentCard) on first use."""
        if self._sdk_client is not None:
            return self._sdk_client

        # Empty supported_transports means "JSON-RPC only" in a2a-sdk
        # (see a2a.client.ClientConfig docstring). The Agno A2A router is
        # JSON-RPC, so this is the right default.
        config = ClientConfig(supported_transports=[])
        self._http_client = AsyncClient(timeout=self.timeout)
        card = await self._get_agent_card_async()
        if card is None:
            # Surface connection / resolution failures through Agno's
            # RemoteServerUnavailableError so existing callers keep working.
            original = getattr(self, "_card_error", None)
            raise RemoteServerUnavailableError(
                message=f"Failed to resolve A2A agent card at {self.base_url}",
                base_url=self.base_url,
                original_error=original,
            )
        factory = ClientFactory(config)
        self._sdk_client = factory.create(card)
        return self._sdk_client

    async def _get_agent_card_async(self) -> Optional[SDKAgentCard]:
        """Resolve the A2A agent card via the a2a-sdk resolver.

        Returns the resolved card on success, or ``None`` on failure.
        When ``None`` is returned, ``self._card_error`` carries the original
        exception so callers can surface it in error messages.
        """
        if self._cached_card is not None:
            return self._cached_card
        if self._http_client is None:
            self._http_client = AsyncClient(timeout=self.timeout)
        try:
            resolver = A2ACardResolver(httpx_client=self._http_client, base_url=self.base_url)
            self._cached_card = await resolver.get_agent_card()
            self._card_error = None
            return self._cached_card
        except Exception as e:
            # Preserve the original error so the caller can surface it
            # in the RemoteServerUnavailableError that wraps the failure.
            self._card_error = e
            return None

    def get_agent_card(self) -> Optional[AgentCard]:
        """Return the A2A agent card synchronously, fetching it if needed.

        This is a thin sync wrapper over ``_get_agent_card_async``; the
        Agno ``Remote`` base class calls this during construction.
        Returns ``None`` if the card cannot be resolved.
        """
        import asyncio

        try:
            return asyncio.run(self._get_agent_card_async())  # type: ignore[return-value]
        except Exception:
            return None

    async def aget_agent_card(self) -> Optional[AgentCard]:
        """Async counterpart of :meth:`get_agent_card`."""
        card = await self._get_agent_card_async()  # type: ignore[return-value]
        if card is None:
            return None
        # ``a2a.types.AgentCard`` and ``agno.client.a2a.schemas.AgentCard`` are
        # both Pydantic models; the Agno schema is a strict subset. We return
        # the SDK object directly and rely on the consumer to read the
        # documented fields (``name``, ``url``, ``description``, ``version``,
        # ``capabilities``, ``metadata``).
        return card  # type: ignore[return-value]

    @staticmethod
    def _build_message(
        message: str,
        *,
        context_id: Optional[str],
        user_id: Optional[str],
        images: Optional[List[Image]],
        audio: Optional[List[Audio]],
        videos: Optional[List[Video]],
        files: Optional[List[File]],
    ) -> A2AMessage:
        """Build an a2a-sdk ``Message`` with the user text and media parts.

        Media handling matches the previous client: each media object is
        represented as a ``FilePart`` whose ``FileWithUri`` carries the
        URL and a generic mime type, which is the same shape the Agno
        A2A server returns.
        """
        parts: List[Part] = [Part(root=TextPart(text=message))]

        def _file_part(url: str, mime: str) -> Part:
            return Part(
                root=FilePart(
                    file=FileWithUri(uri=url, mimeType=mime),
                )
            )

        if images:
            for img in images:
                url = getattr(img, "url", None)
                if url:
                    parts.append(_file_part(url, "image/*"))
        if audio:
            for aud in audio:
                url = getattr(aud, "url", None)
                if url:
                    parts.append(_file_part(url, "audio/*"))
        if videos:
            for vid in videos:
                url = getattr(vid, "url", None)
                if url:
                    parts.append(_file_part(url, "video/*"))
        if files:
            for f in files:
                url = getattr(f, "url", None)
                if url:
                    parts.append(_file_part(url, getattr(f, "mime_type", None) or "application/octet-stream"))

        metadata: Dict[str, Any] = {}
        if user_id:
            metadata["userId"] = user_id

        return A2AMessage(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            context_id=context_id,
            parts=parts,
            metadata=metadata or None,
        )

    def _build_request(
        self,
        *,
        message: str,
        context_id: Optional[str],
        user_id: Optional[str],
        images: Optional[List[Image]],
        audio: Optional[List[Audio]],
        videos: Optional[List[Video]],
        files: Optional[List[File]],
        metadata: Optional[Dict[str, Any]],
    ) -> A2AMessage:
        """Build the user ``A2AMessage`` that ``a2a-sdk`` ``Client.send_message`` accepts."""
        a2a_message = self._build_message(
            message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
        )
        # Merge caller metadata with what _build_message already wrote.
        merged: Dict[str, Any] = dict(metadata or {})
        if user_id and "userId" not in merged:
            merged["userId"] = user_id
        if a2a_message.metadata:
            for k, v in a2a_message.metadata.items():
                merged.setdefault(k, v)
        # ``a2a-sdk``'s ``Client.send_message`` accepts the raw ``Message``;
        # the SDK wraps it in the wire-format JSON-RPC envelope internally.
        if merged:
            a2a_message.metadata = merged
        return a2a_message

    @staticmethod
    def _extract_task(message_or_task: Any) -> Optional[Task]:
        """``Client.send_message`` yields ``(Task, ...)`` tuples or a final ``Message``.

        For tuple form ``(task, status_update, artifact_update)`` we return
        the first element when it is a ``Task``. Bare ``Task`` values are
        returned as-is. Anything else (raw ``Message`` responses) returns
        ``None`` and the caller treats the response as an empty task.
        """
        if isinstance(message_or_task, Task):
            return message_or_task
        if isinstance(message_or_task, tuple) and message_or_task:
            first = message_or_task[0]
            if isinstance(first, Task):
                return first
        return None

    def _build_task_result(self, task: Task, metadata: Optional[Dict[str, Any]]) -> TaskResult:
        """Convert an a2a-sdk ``Task`` into the Agno ``TaskResult``."""
        # ``Task.status.state`` is an enum; we keep the string form for the
        # caller's convenience (it matches the previous implementation).
        state = task.status.state
        status = state.value if isinstance(state, TaskState) else str(state)

        content_parts: List[str] = []
        for msg in task.history or []:
            # ``Message`` discriminator; we only care about agent text.
            if msg.role != Role.agent:
                continue
            for part in msg.parts or []:
                inner = part.root
                # TextPart carries a `.text` field; FilePart / DataPart do not.
                if isinstance(inner, TextPart) and inner.text:
                    content_parts.append(inner.text)

        artifacts: List[Artifact] = []
        for art in task.artifacts or []:
            for part in art.parts or []:
                inner = part.root
                if isinstance(inner, FilePart):
                    file = inner.file
                    artifacts.append(
                        Artifact(
                            artifact_id=art.artifact_id,
                            name=art.name,
                            description=art.description,
                            mime_type=getattr(file, "mime_type", None) or getattr(file, "mimeType", None),
                            uri=getattr(file, "uri", None),
                        )
                    )

        return TaskResult(
            task_id=task.id or "",
            context_id=task.context_id or "",
            status=status,
            content="".join(content_parts),
            artifacts=artifacts,
            metadata=metadata,
        )

    def _build_stream_event(self, response_obj: Any) -> StreamEvent:
        """Convert a streamed a2a-sdk response into an Agno ``StreamEvent``.

        The SDK streams a single ``(Task, status_update, artifact_update)``
        tuple per iteration in non-streaming mode (we iterate it once),
        and a stream of them in streaming mode. We map each shape to a
        flat ``event_type`` string to match the previous client contract.
        """
        # In a2a-sdk 0.3.26, ``Client.send_message`` yields tuples of the form
        # ``(Task, TaskStatusUpdateEvent | None, TaskArtifactUpdateEvent | None)``.
        # Older call sites may also receive a raw ``Message``; tolerate both.
        if isinstance(response_obj, tuple) and response_obj:
            task = response_obj[0]
            status_update = response_obj[1] if len(response_obj) > 1 else None
            artifact_update = response_obj[2] if len(response_obj) > 2 else None
            event_type = "task"
            is_final = True
            if status_update is not None:
                state = getattr(status_update, "state", None) or getattr(status_update, "final", None)
                if state is not None and not getattr(status_update, "final", False):
                    is_final = False
                if isinstance(state, TaskState):
                    event_type = state.value
                elif isinstance(state, str):
                    event_type = state
            if artifact_update is not None:
                event_type = "content"
                is_final = False
            if isinstance(task, Task):
                # Extract text from task.history so streaming consumers see the
                # assistant's text content on the terminal event, not just the
                # task envelope. This matches the previous client contract.
                text: Optional[str] = None
                for msg in task.history or []:
                    if msg.role != Role.agent:
                        continue
                    for part in msg.parts or []:
                        if isinstance(part.root, TextPart) and part.root.text:
                            text = part.root.text
                            break
                    if text is not None:
                        break
                return StreamEvent(
                    event_type=event_type,
                    content=text,
                    task_id=task.id,
                    context_id=task.context_id,
                    metadata=getattr(task, "metadata", None),
                    is_final=is_final,
                )
            return StreamEvent(event_type=event_type, is_final=is_final)

        if isinstance(response_obj, A2AMessage):
            is_reasoning = bool(
                response_obj.metadata and response_obj.metadata.get("agno_content_category") == "reasoning"
            )
            message_text: Optional[str] = None
            for part in response_obj.parts or []:
                p = part.root
                if isinstance(p, TextPart) and p.text:
                    message_text = p.text
                    break
            return StreamEvent(
                event_type="reasoning" if is_reasoning else "content",
                content=message_text,
                task_id=response_obj.task_id,
                context_id=response_obj.context_id,
                metadata=getattr(response_obj, "metadata", None),
                is_final=False,
            )

        return StreamEvent(event_type="unknown")

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
            message: Text message to send.
            context_id: Session/context ID for multi-turn conversations.
            user_id: User identifier (optional).
            images: List of Image objects to include (optional).
            audio: List of Audio objects to include (optional).
            videos: List of Video objects to include (optional).
            files: List of File objects to include (optional).
            metadata: Additional metadata (optional).
            headers: Reserved for callers that need extra HTTP headers. The
                a2a-sdk does not currently expose a per-request headers hook on
                the JSON-RPC transport, so this argument is accepted for
                signature compatibility with the previous client and is
                forwarded into the message metadata when supplied.

        Returns:
            TaskResult with the agent's response.

        Raises:
            RemoteServerUnavailableError: If the connection or request fails.
        """
        a2a_message = self._build_request(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
        )
        if headers and not a2a_message.metadata:
            a2a_message.metadata = dict(headers)

        try:
            client = await self._ensure_sdk_client()
        except RemoteServerUnavailableError:
            raise
        except Exception as e:
            raise RemoteServerUnavailableError(
                message=f"A2A request to {self.base_url} failed: {e}",
                base_url=self.base_url,
                original_error=e,
            ) from e

        try:
            events = [evt async for evt in client.send_message(a2a_message)]
        except Exception as e:
            raise RemoteServerUnavailableError(
                message=f"A2A request to {self.base_url} failed: {e}",
                base_url=self.base_url,
                original_error=e,
            ) from e

        # Aggregate metadata across all events for backward compatibility
        # (the previous client returned ``task.get("metadata")``).
        aggregated_metadata: Optional[Dict[str, Any]] = None
        final_task: Optional[Task] = None
        for evt in events:
            stream_event = self._build_stream_event(evt)
            if stream_event.metadata is not None and aggregated_metadata is None:
                aggregated_metadata = stream_event.metadata
            if stream_event.event_type == "task":
                # Non-streaming mode yields a single tuple; pull the Task.
                extracted = self._extract_task(evt)
                if extracted is not None:
                    final_task = extracted

        if final_task is None:
            # Defensive: if the server did not return a task, surface the
            # last event as a synthetic completed result so callers always
            # get a TaskResult.
            return TaskResult(
                task_id="",
                context_id=context_id or "",
                status="completed",
                content="",
                artifacts=[],
                metadata=aggregated_metadata,
            )
        return self._build_task_result(final_task, aggregated_metadata)

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

        Yields:
            ``StreamEvent`` objects for each event the server emits. The
            final yielded event always has ``is_final=True`` and corresponds
            to the terminal task state.

        Example:
            >>> async for event in client.stream_message("agent", "Hello"):
            ...     if event.is_content and event.content:
            ...         print(event.content, end="", flush=True)
        """
        a2a_message = self._build_request(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            metadata=metadata,
        )
        if headers and not a2a_message.metadata:
            a2a_message.metadata = dict(headers)

        try:
            client = await self._ensure_sdk_client()
        except RemoteServerUnavailableError:
            raise
        except Exception as e:
            raise RemoteServerUnavailableError(
                message=f"A2A stream to {self.base_url} failed: {e}",
                base_url=self.base_url,
                original_error=e,
            ) from e

        try:
            async for evt in client.send_message(a2a_message):
                yield self._build_stream_event(evt)
        except Exception as e:
            raise RemoteServerUnavailableError(
                message=f"A2A stream to {self.base_url} failed: {e}",
                base_url=self.base_url,
                original_error=e,
            ) from e

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Call this on application shutdown."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._sdk_client = None
            self._cached_card = None

"""A2AClient — bind one remote A2A 1.0 agent as an Agno toolkit, via the official `a2a-sdk` client.

One toolkit instance per remote agent, with a connect()/close() lifecycle,
an `initialized` property and async context manager support. Tool names are
derived from the remote agent's URL slug so several A2AClient toolkit instances
can coexist on one Agno agent.
"""

import asyncio
import json
import re
from typing import Optional
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_warning

try:
    import httpx
    from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory, create_client
    from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, TaskState
    from google.protobuf import json_format
except ImportError as e:
    raise ImportError(
        "`a2a-sdk>=1.0` is required for A2AClient. "
        "Install with `pip install -U 'a2a-sdk>=1.0'` (or install agno with the `a2a` extra)."
    ) from e


def _slug_from_url(url: str) -> str:
    """Derive a stable identifier from the remote agent URL's last path segment.

    e.g. "http://host/a2a/agents/weather-reporter-agent" -> "weather_reporter_agent"
    """
    segment = url.rstrip("/").split("/")[-1] or "agent"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", segment).strip("_").lower()
    return slug or "agent"


class A2AClient(Toolkit):
    """Toolkit binding ONE remote A2A 1.0 agent.

    Give each remote agent its own instance; the tool names carry the agent's
    URL slug so an Agno agent can hold several instances without collisions:

        weather = A2AClient(url="http://localhost:7770/a2a/agents/weather-reporter-agent")
        airbnb = A2AClient(url="http://localhost:7774/a2a/agents/airbnb-search-agent")
        Agent(tools=[weather, airbnb])
        # -> tools: send_message_to_weather_reporter_agent, send_message_to_airbnb_search_agent, ...

    Lifecycle: `await toolkit.connect()` (or `async with toolkit:`) resolves the
    AgentCard once, opens a persistent official-SDK client and enriches the
    tool descriptions from the card. Tools also connect lazily on first use, so
    explicit lifecycle management is optional. `await toolkit.close()` releases
    the connection.

    Sync tool variants run one-shot clients per call (safe outside event loops).
    """

    def __init__(
        self,
        url: str,
        *,
        name: Optional[str] = None,
        timeout: float = 60.0,
        enable_send_message: bool = True,
        enable_get_agent_card: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Args:
            url: Base URL of the remote agent
                (e.g. `http://localhost:7777/a2a/agents/basic_agent`). The SDK
                resolves `/.well-known/agent-card.json` from here.
            name: Toolkit name. Defaults to a stable name derived from the URL
                (`a2a_<agent-slug>`), so multiple A2A toolkits stay distinguishable.
            timeout: HTTP timeout in seconds.
            enable_send_message: Register the `send_message_to_<slug>` tool.
            enable_get_agent_card: Register the `get_<slug>_card` tool.
            all: If True, enable every tool regardless of individual flags.
        """
        self.url: str = url.rstrip("/")
        self.timeout: float = timeout
        self.agent_slug: str = _slug_from_url(self.url)

        super().__init__(name=name or f"a2a_{self.agent_slug}", **kwargs)

        self._initialized: bool = False
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self._client: Optional[Client] = None
        self._agent_card: Optional[AgentCard] = None

        self.send_message_tool_name = f"send_message_to_{self.agent_slug}"
        self.get_agent_card_tool_name = f"get_{self.agent_slug}_card"

        if all or enable_send_message:
            self.register(self.send_message, name=self.send_message_tool_name)
            self.register(self.asend_message, name=self.send_message_tool_name)
        if all or enable_get_agent_card:
            self.register(self.get_agent_card, name=self.get_agent_card_tool_name)
            self.register(self.aget_agent_card, name=self.get_agent_card_tool_name)

    @property
    def initialized(self) -> bool:
        return self._initialized

    # --- lifecycle ------------------------------------------------------------------

    async def connect(self, force: bool = False) -> None:
        """Resolve the remote AgentCard and open a persistent SDK client."""
        if force:
            await self.close()
        if self._initialized:
            return

        self._httpx_client = httpx.AsyncClient(timeout=self.timeout)
        try:
            resolver = A2ACardResolver(httpx_client=self._httpx_client, base_url=self.url)
            self._agent_card = await resolver.get_agent_card()
            self._client = ClientFactory(ClientConfig(streaming=True, httpx_client=self._httpx_client)).create(
                self._agent_card
            )
        except Exception:
            await self.close()
            raise

        self._apply_card_to_tools()
        self._initialized = True
        log_debug(f"A2AClient connected to {self.url} ({self._agent_card.name})")

    async def close(self) -> None:
        """Close the SDK client and release the HTTP connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if self._httpx_client is not None:
            try:
                await self._httpx_client.aclose()
            except Exception:
                pass
            self._httpx_client = None
        self._agent_card = None
        self._initialized = False

    async def __aenter__(self) -> "A2AClient":
        await self.connect()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.close()

    def _apply_card_to_tools(self) -> None:
        """Enrich registered tool descriptions with the resolved AgentCard."""
        if self._agent_card is None:
            return
        agent_name = self._agent_card.name or self.agent_slug
        agent_description = (self._agent_card.description or "").strip()
        send_description = f"Send a message to the remote agent '{agent_name}' and get its response."
        if agent_description:
            send_description += f" {agent_name}: {agent_description}"
        card_description = f"Fetch the A2A AgentCard of '{agent_name}' (its skills and capabilities)."

        for registry in (self.functions, self.async_functions):
            if self.send_message_tool_name in registry:
                registry[self.send_message_tool_name].description = send_description
            if self.get_agent_card_tool_name in registry:
                registry[self.get_agent_card_tool_name].description = card_description

    # --- tools ----------------------------------------------------------------------

    async def asend_message(self, message: str) -> str:
        """Send a message to the remote A2A agent and return its final response text.

        The response stream is consumed end-to-end: `artifact_update` chunks are
        accumulated and the terminal `Task` is preferred for the returned text.
        FAILED/CANCELED/REJECTED terminal states are surfaced as errors.

        Args:
            message: The user message to send to the remote agent.
        """
        if not message:
            return "Error: message must be non-empty."
        try:
            if not self._initialized:
                await self.connect()
            assert self._client is not None
            return await self._consume_send(self._client, message)
        except Exception as e:
            log_warning(f"A2AClient.asend_message failed: {type(e).__name__}: {e}")
            return f"Error talking to {self.url}: {e}"

    def send_message(self, message: str) -> str:
        """Sync variant of `asend_message` — see that method for docs."""

        async def _one_shot() -> str:
            if not message:
                return "Error: message must be non-empty."
            client = await create_client(self.url)
            async with client:
                return await self._consume_send(client, message)

        try:
            return asyncio.run(_one_shot())
        except Exception as e:
            log_warning(f"A2AClient.send_message failed: {type(e).__name__}: {e}")
            return f"Error talking to {self.url}: {e}"

    async def aget_agent_card(self) -> str:
        """Fetch the remote agent's AgentCard as pretty-printed JSON.

        Use this to inspect the remote agent's name, description, skills and
        protocol bindings before delegating work to it.
        """
        try:
            if not self._initialized:
                await self.connect()
            assert self._agent_card is not None
            return json.dumps(
                json_format.MessageToDict(self._agent_card, preserving_proto_field_name=False),
                indent=2,
            )
        except Exception as e:
            log_warning(f"A2AClient.aget_agent_card failed: {type(e).__name__}: {e}")
            return f"Error fetching agent card from {self.url}: {e}"

    def get_agent_card(self) -> str:
        """Sync variant of `aget_agent_card` — see that method for docs."""

        async def _one_shot() -> str:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                resolver = A2ACardResolver(httpx_client=http, base_url=self.url)
                card = await resolver.get_agent_card()
                return json.dumps(
                    json_format.MessageToDict(card, preserving_proto_field_name=False),
                    indent=2,
                )

        try:
            return asyncio.run(_one_shot())
        except Exception as e:
            log_warning(f"A2AClient.get_agent_card failed: {type(e).__name__}: {e}")
            return f"Error fetching agent card from {self.url}: {e}"

    # --- stream consumption -----------------------------------------------------------

    @staticmethod
    async def _consume_send(client: Client, message: str) -> str:
        request = SendMessageRequest(
            message=Message(
                message_id=str(uuid4()),
                role=Role.ROLE_USER,
                parts=[Part(text=message, media_type="text/plain")],
            )
        )
        accumulated: str = ""
        final_text: Optional[str] = None
        terminal_error: Optional[str] = None
        async for resp in client.send_message(request):
            kind = resp.WhichOneof("payload")
            if kind == "artifact_update":
                for p in resp.artifact_update.artifact.parts:
                    if p.WhichOneof("content") == "text":
                        accumulated += p.text
            elif kind == "message":
                for p in resp.message.parts:
                    if p.WhichOneof("content") == "text":
                        accumulated += p.text
            elif kind == "task":
                task_text = ""
                if resp.task.history:
                    last = resp.task.history[-1]
                    task_text = "".join(p.text for p in last.parts if p.WhichOneof("content") == "text")
                # A FAILED/CANCELED/REJECTED task's history holds an error notice,
                # not an answer — surface it as an error so the calling LLM does
                # not treat it as a successful response.
                state = resp.task.status.state
                if state == TaskState.TASK_STATE_FAILED:
                    terminal_error = f"Error: remote agent failed: {task_text or 'no details provided'}"
                elif state == TaskState.TASK_STATE_CANCELED:
                    terminal_error = f"Error: remote agent run was cancelled: {task_text or 'no details provided'}"
                elif state == TaskState.TASK_STATE_REJECTED:
                    terminal_error = f"Error: remote agent rejected the request: {task_text or 'no details provided'}"
                elif task_text:
                    final_text = task_text
        if terminal_error:
            return terminal_error
        return final_text or accumulated or "(no text returned)"


# Backwards-compatible alias for the pre-rename toolkit class name.
A2AClientTools = A2AClient

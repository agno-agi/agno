"""A2AClientTools — call any A2A 1.0 agent as an Agno tool, via the official `a2a-sdk` client."""

import asyncio
import json
from typing import Any, Callable, List, Optional, Tuple
from uuid import uuid4

from agno.tools import Toolkit
from agno.utils.log import log_warning

try:
    import httpx
    from a2a.client import A2ACardResolver, create_client
    from a2a.types import Message, Part, Role, SendMessageRequest
    from google.protobuf import json_format
except ImportError as e:
    raise ImportError(
        "`a2a-sdk>=1.0` is required for A2AClientTools. "
        "Install with `pip install -U 'a2a-sdk>=1.0'` (or install agno with the `a2a` extra)."
    ) from e


class A2AClientTools(Toolkit):
    """Toolkit that lets an Agno agent call any A2A 1.0 agent over the wire.

    Wraps the official `a2a-sdk` client (`a2a.client.create_client`,
    `A2ACardResolver`) so the LLM can:

    - `get_agent_card(agent_url)`: discover what a remote agent does.
    - `send_message(agent_url, message)`: send a message and get the final response.

    `agent_url` is the *base URL* of the agent (e.g.
    `http://localhost:7777/a2a/agents/basic_agent`); the SDK resolves
    `/.well-known/agent-card.json` itself.

    The toolkit is async-native; sync wrappers run a private event loop via
    `asyncio.run`.
    """

    def __init__(
        self,
        default_agent_url: Optional[str] = None,
        timeout: float = 60.0,
        enable_send_message: bool = True,
        enable_get_agent_card: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Args:
            default_agent_url: If set, methods can be called without `agent_url`
                and will target this URL. Useful when the toolkit is bound to a
                single remote agent.
            timeout: HTTP timeout in seconds for agent-card resolution.
            enable_send_message: Register the `send_message` tool.
            enable_get_agent_card: Register the `get_agent_card` tool.
            all: If True, enable every tool regardless of individual flags.
        """
        self.default_agent_url: Optional[str] = default_agent_url.rstrip("/") if default_agent_url else None
        self.timeout: float = timeout

        tools: List[Callable[..., Any]] = []
        async_tools: List[Tuple[Callable[..., Any], str]] = []
        if all or enable_send_message:
            tools.append(self.send_message)
            async_tools.append((self.asend_message, "send_message"))
        if all or enable_get_agent_card:
            tools.append(self.get_agent_card)
            async_tools.append((self.aget_agent_card, "get_agent_card"))

        super().__init__(name="a2a_client_tools", tools=tools, async_tools=async_tools, **kwargs)

    def _resolve_url(self, agent_url: Optional[str]) -> str:
        target = agent_url or self.default_agent_url
        if not target:
            raise ValueError(
                "agent_url is required (pass it to the tool or set `default_agent_url` at A2AClientTools init time)."
            )
        return target.rstrip("/")

    async def asend_message(self, agent_url: Optional[str] = None, message: str = "") -> str:
        """Send a message to an A2A 1.0 agent and return its final response text.

        The agent's response is consumed end-to-end: streaming `artifact_update`
        chunks are accumulated, and the final `Task` history is preferred for
        the returned text.

        Args:
            agent_url: Base URL of the remote agent
                (e.g. `http://localhost:7777/a2a/agents/basic_agent`).
                Optional if `default_agent_url` was provided to A2AClientTools.
            message: The user message to send.
        """
        if not message:
            return "Error: message must be non-empty."
        url = self._resolve_url(agent_url)
        try:
            req = SendMessageRequest(
                message=Message(
                    message_id=str(uuid4()),
                    role=Role.ROLE_USER,
                    parts=[Part(text=message, media_type="text/plain")],
                )
            )
            client = await create_client(url)
            accumulated: str = ""
            final_text: Optional[str] = None
            async with client:
                async for resp in client.send_message(req):
                    kind = resp.WhichOneof("payload")
                    if kind == "artifact_update":
                        for p in resp.artifact_update.artifact.parts:
                            if p.WhichOneof("content") == "text":
                                accumulated += p.text
                    elif kind == "message":
                        for p in resp.message.parts:
                            if p.WhichOneof("content") == "text":
                                accumulated += p.text
                    elif kind == "task" and resp.task.history:
                        last = resp.task.history[-1]
                        final_text = "".join(p.text for p in last.parts if p.WhichOneof("content") == "text")
            return final_text or accumulated or "(no text returned)"
        except Exception as e:
            log_warning(f"A2AClientTools.asend_message failed: {type(e).__name__}: {e}")
            return f"Error talking to {url}: {e}"

    def send_message(self, agent_url: Optional[str] = None, message: str = "") -> str:
        """Sync wrapper around `asend_message` — see that method for docs."""
        return asyncio.run(self.asend_message(agent_url=agent_url, message=message))

    async def aget_agent_card(self, agent_url: Optional[str] = None) -> str:
        """Fetch the AgentCard from an A2A 1.0 agent's `/.well-known/agent-card.json`.

        Returns a pretty-printed JSON string of the card so the LLM can inspect
        the agent's name, description, skills, and protocol bindings.

        Args:
            agent_url: Base URL of the remote agent. Optional if
                `default_agent_url` was provided.
        """
        url = self._resolve_url(agent_url)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                resolver = A2ACardResolver(httpx_client=http, base_url=url)
                card = await resolver.get_agent_card()
                return json.dumps(
                    json_format.MessageToDict(card, preserving_proto_field_name=False),
                    indent=2,
                )
        except Exception as e:
            log_warning(f"A2AClientTools.aget_agent_card failed: {type(e).__name__}: {e}")
            return f"Error fetching agent card from {url}: {e}"

    def get_agent_card(self, agent_url: Optional[str] = None) -> str:
        """Sync wrapper around `aget_agent_card` — see that method for docs."""
        return asyncio.run(self.aget_agent_card(agent_url=agent_url))

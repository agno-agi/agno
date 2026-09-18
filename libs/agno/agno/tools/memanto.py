"""
Memanto Tools
=============
Toolkit and HTTP client for Memanto (Moorcheh-backed semantic memory).

Requires a running Memanto server (`memanto serve`) with Moorcheh configured.
Auth uses a session token from Activate Agent (`X-Session-Token`).

See: https://docs.memanto.ai/getting-started/introduction
"""

from __future__ import annotations

from os import getenv
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    import httpx
except ImportError as e:  # pragma: no cover
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`") from e

DEFAULT_MEMANTO_URL = "http://localhost:8000"
DEFAULT_API_PREFIX = "/api/v2"

VALID_MEMORY_TYPES = frozenset(
    {
        "fact",
        "preference",
        "goal",
        "decision",
        "artifact",
        "learning",
        "event",
        "instruction",
        "relationship",
        "context",
        "observation",
        "commitment",
        "error",
    }
)

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to Memanto long-term semantic memory. Use these tools:
    - `remember`: Store durable facts, preferences, decisions, or instructions.
    - `recall`: Search memories by natural language relevance.
    - `answer_from_memory`: Get a synthesized answer grounded only in stored memories.
    - `recall_recent`: List the most recently stored memories.

    Guidelines:
    - Prefer `recall` before asking the user to repeat known preferences or facts.
    - Use `remember` for information that should persist across sessions.
    - For `remember`, pass exactly ONE memory_type: fact, preference, goal, decision, or instruction.
      Do not pass multiple types (wrong: "fact, preference"; right: "preference").
    """
)


def normalize_memory_type(memory_type: str) -> str:
    """Map LLM output to a single valid Memanto memory type."""
    if not memory_type:
        return "fact"

    raw = str(memory_type).strip().lower()
    if raw in VALID_MEMORY_TYPES:
        return raw

    # Models sometimes pass "fact, preference" — prefer a specific type over generic fact.
    parts = [p.strip() for p in raw.replace("/", ",").split(",") if p.strip()]
    for part in parts:
        if part in VALID_MEMORY_TYPES and part != "fact":
            return part
    for part in parts:
        if part in VALID_MEMORY_TYPES:
            return part

    for valid_type in VALID_MEMORY_TYPES:
        if raw.startswith(valid_type):
            return valid_type

    return "fact"


def clamp_confidence(confidence: float) -> float:
    """Keep confidence within Memanto's 0-1 range."""
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0.9
    return max(0.0, min(1.0, value))


# =============================================================================
# HTTP client
# =============================================================================


class MemantoClient:
    """Synchronous Memanto REST client with lazy session activation."""

    def __init__(
        self,
        agent_id: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        auto_activate: bool = True,
        session_token: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.base_url = (base_url or getenv("MEMANTO_URL") or DEFAULT_MEMANTO_URL).rstrip("/")
        self.timeout = timeout
        self.auto_activate = auto_activate
        self.session_token = session_token or getenv("MEMANTO_SESSION_TOKEN")
        self._client = httpx.Client(timeout=timeout)

    @property
    def _api_base(self) -> str:
        return f"{self.base_url}{DEFAULT_API_PREFIX}"

    @property
    def _agent_base(self) -> str:
        return f"{self._api_base}/agents/{self.agent_id}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.session_token:
            headers["X-Session-Token"] = self.session_token
        return headers

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MemantoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def ensure_session(self) -> str:
        """Activate a session if no token is set. Returns the session token."""
        if self.session_token:
            return self.session_token
        if not self.auto_activate:
            raise ValueError(
                "No Memanto session token. Call activate() or set MEMANTO_SESSION_TOKEN / pass session_token."
            )
        return self.activate()

    def activate(self) -> str:
        """Start a session for the agent and store the session token."""
        url = f"{self._agent_base}/activate"
        log_debug(f"Activating Memanto agent session: {self.agent_id}")
        response = self._client.post(url)
        response.raise_for_status()
        data = response.json()
        token = data.get("session_token")
        if not token:
            raise ValueError(f"Memanto activate response missing session_token: {data}")
        self.session_token = token
        return token

    def deactivate(self) -> Dict[str, Any]:
        """End the active session for the agent."""
        self.ensure_session()
        url = f"{self._agent_base}/deactivate"
        response = self._client.post(url, headers=self._headers())
        response.raise_for_status()
        self.session_token = None
        return response.json()

    def remember(
        self,
        content: str,
        memory_type: str = "fact",
        title: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        provenance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a single memory."""
        self.ensure_session()
        payload: Dict[str, Any] = {"content": content, "type": memory_type}
        if title is not None:
            payload["title"] = title
        if confidence is not None:
            payload["confidence"] = confidence
        if tags is not None:
            payload["tags"] = tags
        if source is not None:
            payload["source"] = source
        if provenance is not None:
            payload["provenance"] = provenance

        url = f"{self._agent_base}/remember"
        response = self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        return response.json()

    def batch_remember(self, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Store up to 100 memories in one request."""
        self.ensure_session()
        url = f"{self._agent_base}/batch-remember"
        response = self._client.post(url, headers=self._headers(), json={"memories": memories})
        response.raise_for_status()
        return response.json()

    def recall(
        self,
        query: str,
        limit: int = 10,
        memory_types: Optional[List[str]] = None,
        min_similarity: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search across stored memories."""
        self.ensure_session()
        payload: Dict[str, Any] = {"query": query, "limit": limit}
        if memory_types is not None:
            payload["type"] = memory_types
        if min_similarity is not None:
            payload["min_similarity"] = min_similarity

        url = f"{self._agent_base}/recall"
        response = self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        memories = data.get("memories", data if isinstance(data, list) else [])
        return memories if isinstance(memories, list) else []

    def recall_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recently stored memories."""
        self.ensure_session()
        url = f"{self._agent_base}/recall-recent"
        response = self._client.post(url, headers=self._headers(), json={"limit": limit})
        response.raise_for_status()
        data = response.json()
        memories = data.get("memories", data if isinstance(data, list) else [])
        return memories if isinstance(memories, list) else []

    def answer(
        self,
        question: str,
        limit: Optional[int] = None,
        temperature: Optional[float] = None,
        kiosk_mode: bool = False,
    ) -> str:
        """Generate an LLM answer grounded in stored memories."""
        self.ensure_session()
        payload: Dict[str, Any] = {"question": question, "kiosk_mode": kiosk_mode}
        if limit is not None:
            payload["limit"] = limit
        if temperature is not None:
            payload["temperature"] = temperature

        url = f"{self._agent_base}/answer"
        response = self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data.get("answer", ""))


class AsyncMemantoClient:
    """Async Memanto REST client with lazy session activation."""

    def __init__(
        self,
        agent_id: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        auto_activate: bool = True,
        session_token: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.base_url = (base_url or getenv("MEMANTO_URL") or DEFAULT_MEMANTO_URL).rstrip("/")
        self.timeout = timeout
        self.auto_activate = auto_activate
        self.session_token = session_token or getenv("MEMANTO_SESSION_TOKEN")
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def _api_base(self) -> str:
        return f"{self.base_url}{DEFAULT_API_PREFIX}"

    @property
    def _agent_base(self) -> str:
        return f"{self._api_base}/agents/{self.agent_id}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.session_token:
            headers["X-Session-Token"] = self.session_token
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncMemantoClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def ensure_session(self) -> str:
        if self.session_token:
            return self.session_token
        if not self.auto_activate:
            raise ValueError(
                "No Memanto session token. Call activate() or set MEMANTO_SESSION_TOKEN / pass session_token."
            )
        return await self.activate()

    async def activate(self) -> str:
        url = f"{self._agent_base}/activate"
        log_debug(f"Activating Memanto agent session: {self.agent_id}")
        response = await self._client.post(url)
        response.raise_for_status()
        data = response.json()
        token = data.get("session_token")
        if not token:
            raise ValueError(f"Memanto activate response missing session_token: {data}")
        self.session_token = token
        return token

    async def deactivate(self) -> Dict[str, Any]:
        await self.ensure_session()
        url = f"{self._agent_base}/deactivate"
        response = await self._client.post(url, headers=self._headers())
        response.raise_for_status()
        self.session_token = None
        return response.json()

    async def remember(
        self,
        content: str,
        memory_type: str = "fact",
        title: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        provenance: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.ensure_session()
        payload: Dict[str, Any] = {"content": content, "type": memory_type}
        if title is not None:
            payload["title"] = title
        if confidence is not None:
            payload["confidence"] = confidence
        if tags is not None:
            payload["tags"] = tags
        if source is not None:
            payload["source"] = source
        if provenance is not None:
            payload["provenance"] = provenance

        url = f"{self._agent_base}/remember"
        response = await self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        return response.json()

    async def batch_remember(self, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        await self.ensure_session()
        url = f"{self._agent_base}/batch-remember"
        response = await self._client.post(url, headers=self._headers(), json={"memories": memories})
        response.raise_for_status()
        return response.json()

    async def recall(
        self,
        query: str,
        limit: int = 10,
        memory_types: Optional[List[str]] = None,
        min_similarity: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        await self.ensure_session()
        payload: Dict[str, Any] = {"query": query, "limit": limit}
        if memory_types is not None:
            payload["type"] = memory_types
        if min_similarity is not None:
            payload["min_similarity"] = min_similarity

        url = f"{self._agent_base}/recall"
        response = await self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        memories = data.get("memories", data if isinstance(data, list) else [])
        return memories if isinstance(memories, list) else []

    async def recall_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        await self.ensure_session()
        url = f"{self._agent_base}/recall-recent"
        response = await self._client.post(url, headers=self._headers(), json={"limit": limit})
        response.raise_for_status()
        data = response.json()
        memories = data.get("memories", data if isinstance(data, list) else [])
        return memories if isinstance(memories, list) else []

    async def answer(
        self,
        question: str,
        limit: Optional[int] = None,
        temperature: Optional[float] = None,
        kiosk_mode: bool = False,
    ) -> str:
        await self.ensure_session()
        payload: Dict[str, Any] = {"question": question, "kiosk_mode": kiosk_mode}
        if limit is not None:
            payload["limit"] = limit
        if temperature is not None:
            payload["temperature"] = temperature

        url = f"{self._agent_base}/answer"
        response = await self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data.get("answer", ""))


def memory_content(memory: Union[Dict[str, Any], str]) -> str:
    """Extract displayable content from a Memanto memory payload."""
    if isinstance(memory, str):
        return memory
    for key in ("content", "text", "memory", "value"):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return str(memory)


def format_memories(memories: List[Dict[str, Any]], header: str = "Relevant Memanto memories") -> str:
    """Format recalled memories into a prompt-friendly string."""
    if not memories:
        return ""
    lines = ["<memanto_memories>", f"{header}:"]
    for memory in memories:
        content = memory_content(memory)
        memory_type = memory.get("type") if isinstance(memory, dict) else None
        if memory_type:
            lines.append(f"- [{memory_type}] {content}")
        else:
            lines.append(f"- {content}")
    lines.append("</memanto_memories>")
    return "\n".join(lines)


# =============================================================================
# Toolkit
# =============================================================================


class MemantoTools(Toolkit):
    """Sync toolkit wrapping Memanto remember / recall / answer APIs."""

    def __init__(
        self,
        agent_id: Optional[str] = None,
        base_url: Optional[str] = None,
        session_token: Optional[str] = None,
        enable_remember: bool = True,
        enable_recall: bool = True,
        enable_answer: bool = True,
        enable_recall_recent: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        all: bool = False,
        client: Optional[MemantoClient] = None,
        **kwargs: Any,
    ):
        self.agent_id = agent_id or getenv("MEMANTO_AGENT_ID") or "agno-agent"
        self.base_url = base_url or getenv("MEMANTO_URL")
        self.session_token = session_token or getenv("MEMANTO_SESSION_TOKEN")
        self._client = client
        self._initialized = False

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"
        else:
            self.instructions = instructions

        tools: List[Any] = []
        if enable_remember or all:
            tools.append(self.remember)
        if enable_recall or all:
            tools.append(self.recall)
        if enable_answer or all:
            tools.append(self.answer_from_memory)
        if enable_recall_recent or all:
            tools.append(self.recall_recent)

        super().__init__(
            name="memanto_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

        self.initialize()

    def _get_client(self) -> MemantoClient:
        if self._client is None:
            self._client = MemantoClient(
                agent_id=self.agent_id,
                base_url=self.base_url,
                session_token=self.session_token,
            )
        return self._client

    def initialize(self) -> bool:
        """Activate a Memanto session if needed."""
        if self._initialized and self._client is not None and self._client.session_token:
            return True
        try:
            client = self._get_client()
            client.ensure_session()
            self.session_token = client.session_token
            self._initialized = True
            log_debug(f"MemantoTools initialized for agent {self.agent_id}")
            return True
        except Exception as e:
            log_error(f"Failed to initialize MemantoTools: {e}")
            self._initialized = False
            return False

    def remember(
        self,
        content: str,
        memory_type: str = "fact",
        confidence: float = 0.9,
        tags: Optional[str] = None,
    ) -> str:
        """Store a durable memory in Memanto.

        Args:
            content: Memory text to store.
            memory_type: Exactly one Memanto type: fact, preference, goal, decision, or instruction.
            confidence: Confidence between 0 and 1.
            tags: Optional comma-separated tags.
        """
        if not self._initialized and not self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
            normalized_type = normalize_memory_type(memory_type)
            result = self._get_client().remember(
                content=content,
                memory_type=normalized_type,
                confidence=clamp_confidence(confidence),
                tags=tag_list,
                source="agent",
                provenance="explicit_statement",
            )
            memory_id = result.get("memory_id", "unknown")
            return f"Stored Memanto memory ({memory_id}) as {normalized_type}: {content}"
        except Exception as e:
            log_error(f"Memanto remember failed: {e}")
            return f"Error storing memory: {e}"

    def recall(self, query: str, limit: int = 5) -> str:
        """Search Memanto memories by semantic relevance.

        Args:
            query: Natural-language search query.
            limit: Max memories to return.
        """
        if not self._initialized and not self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            memories = self._get_client().recall(query=query, limit=limit)
            if not memories:
                return f"No Memanto memories found for query: {query}"
            return format_memories(memories) or f"No Memanto memories found for query: {query}"
        except Exception as e:
            log_error(f"Memanto recall failed: {e}")
            return f"Error recalling memories: {e}"

    def answer_from_memory(self, question: str) -> str:
        """Answer a question using only Memanto-stored memories (RAG).

        Args:
            question: Question to answer from memory.
        """
        if not self._initialized and not self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            answer = self._get_client().answer(question=question)
            return answer or "No answer available from Memanto memories."
        except Exception as e:
            log_error(f"Memanto answer failed: {e}")
            return f"Error generating memory answer: {e}"

    def recall_recent(self, limit: int = 10) -> str:
        """Return the most recently stored Memanto memories.

        Args:
            limit: Max memories to return.
        """
        if not self._initialized and not self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            memories = self._get_client().recall_recent(limit=limit)
            if not memories:
                return "No recent Memanto memories found."
            return format_memories(memories, header="Recent Memanto memories") or "No recent Memanto memories found."
        except Exception as e:
            log_error(f"Memanto recall_recent failed: {e}")
            return f"Error recalling recent memories: {e}"


class MemantoAsyncTools(Toolkit):
    """Async toolkit wrapping Memanto remember / recall / answer APIs."""

    def __init__(
        self,
        agent_id: Optional[str] = None,
        base_url: Optional[str] = None,
        session_token: Optional[str] = None,
        enable_remember: bool = True,
        enable_recall: bool = True,
        enable_answer: bool = True,
        enable_recall_recent: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        all: bool = False,
        client: Optional[AsyncMemantoClient] = None,
        **kwargs: Any,
    ):
        self.agent_id = agent_id or getenv("MEMANTO_AGENT_ID") or "agno-agent"
        self.base_url = base_url or getenv("MEMANTO_URL")
        self.session_token = session_token or getenv("MEMANTO_SESSION_TOKEN")
        self._client = client
        self._initialized = False

        if instructions is None:
            self.instructions = "<Memory Instructions>\n" + DEFAULT_INSTRUCTIONS + "\n</Memory Instructions>"
        else:
            self.instructions = instructions

        tools: List[Any] = []
        if enable_remember or all:
            tools.append(self.remember)
        if enable_recall or all:
            tools.append(self.recall)
        if enable_answer or all:
            tools.append(self.answer_from_memory)
        if enable_recall_recent or all:
            tools.append(self.recall_recent)

        super().__init__(
            name="memanto_async_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def _get_client(self) -> AsyncMemantoClient:
        if self._client is None:
            self._client = AsyncMemantoClient(
                agent_id=self.agent_id,
                base_url=self.base_url,
                session_token=self.session_token,
            )
        return self._client

    async def initialize(self) -> bool:
        if self._initialized and self._client is not None and self._client.session_token:
            return True
        try:
            client = self._get_client()
            await client.ensure_session()
            self.session_token = client.session_token
            self._initialized = True
            log_debug(f"MemantoAsyncTools initialized for agent {self.agent_id}")
            return True
        except Exception as e:
            log_error(f"Failed to initialize MemantoAsyncTools: {e}")
            self._initialized = False
            return False

    async def remember(
        self,
        content: str,
        memory_type: str = "fact",
        confidence: float = 0.9,
        tags: Optional[str] = None,
    ) -> str:
        """Store a durable memory in Memanto."""
        if not self._initialized and not await self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
            normalized_type = normalize_memory_type(memory_type)
            result = await self._get_client().remember(
                content=content,
                memory_type=normalized_type,
                confidence=clamp_confidence(confidence),
                tags=tag_list,
                source="agent",
                provenance="explicit_statement",
            )
            memory_id = result.get("memory_id", "unknown")
            return f"Stored Memanto memory ({memory_id}) as {normalized_type}: {content}"
        except Exception as e:
            log_error(f"Memanto remember failed: {e}")
            return f"Error storing memory: {e}"

    async def recall(self, query: str, limit: int = 5) -> str:
        """Search Memanto memories by semantic relevance."""
        if not self._initialized and not await self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            memories = await self._get_client().recall(query=query, limit=limit)
            if not memories:
                return f"No Memanto memories found for query: {query}"
            return format_memories(memories) or f"No Memanto memories found for query: {query}"
        except Exception as e:
            log_error(f"Memanto recall failed: {e}")
            return f"Error recalling memories: {e}"

    async def answer_from_memory(self, question: str) -> str:
        """Answer a question using only Memanto-stored memories (RAG)."""
        if not self._initialized and not await self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            answer = await self._get_client().answer(question=question)
            return answer or "No answer available from Memanto memories."
        except Exception as e:
            log_error(f"Memanto answer failed: {e}")
            return f"Error generating memory answer: {e}"

    async def recall_recent(self, limit: int = 10) -> str:
        """Return the most recently stored Memanto memories."""
        if not self._initialized and not await self.initialize():
            return "Error: Memanto client/session not initialized."

        try:
            memories = await self._get_client().recall_recent(limit=limit)
            if not memories:
                return "No recent Memanto memories found."
            return format_memories(memories, header="Recent Memanto memories") or "No recent Memanto memories found."
        except Exception as e:
            log_error(f"Memanto recall_recent failed: {e}")
            return f"Error recalling recent memories: {e}"

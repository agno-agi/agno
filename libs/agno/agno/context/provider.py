"""
Context Providers
=================

A `ContextProvider` exposes a source of information — a folder of files,
the web, a database, an MCP server — to an agent. Subclasses implement:

- `query(question)` / `aquery(question)` — natural-language access; returns an `Answer`
- `status()` / `astatus()` — is the source reachable?

Providers that support writes also override `aupdate()` (and optionally
`update()`); the default raises `NotImplementedError` so read-only
providers inherit a clean failure that `_update_tool()` surfaces as "<name> is read-only".

`mode` controls how the provider surfaces itself to the calling agent:

- `ContextMode.default` — the provider's recommended exposure; each
  subclass decides what this means
- `ContextMode.agent` — wraps the provider behind a sub-agent; the
  calling agent gets a single `query_<id>` tool
- `ContextMode.tools` — exposes the provider's underlying tools directly;
  the calling agent orchestrates them itself

`model` swaps the model used by the internal sub-agent. For full
customization, subclass and override `_build_agent()`.

`instructions()` returns mode-aware usage guidance. The wiring layer
chooses how to surface it: inline in the system prompt, or via an
on-demand `learn_context(id)` meta-tool.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from agno.context.mode import ContextMode
from agno.run import RunContext
from agno.tools import tool

if TYPE_CHECKING:
    from agno.models.base import Model


@dataclass
class Status:
    """Health of a context provider."""

    ok: bool
    detail: str = ""


@dataclass
class Document:
    """A piece of content available through a provider."""

    id: str
    name: str
    uri: str | None = None
    source: str | None = None
    snippet: str | None = None


@dataclass
class Answer:
    """What query() returns."""

    results: list[Document] = field(default_factory=list)
    text: str | None = None


class ContextProvider(ABC):
    """Base class for every context provider."""

    def __init__(
        self,
        id: str,
        *,
        name: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        query_tool_name: str | None = None,
        update_tool_name: str | None = None,
    ) -> None:
        self.id = id
        self.name = name or id
        self.mode = mode
        self.model = model
        self.query_tool_name = query_tool_name or f"query_{_sanitize_id(id)}"
        self.update_tool_name = update_tool_name or f"update_{_sanitize_id(id)}"

    @abstractmethod
    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer: ...

    @abstractmethod
    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer: ...

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        """Apply a natural-language write. Default: read-only.

        Override for providers that support writes (e.g. a database or
        inbox). The base raises `NotImplementedError` so `_update_tool`
        can report "<name> is read-only" to the calling agent.

        ``run_context`` carries the caller agent's user_id, session_id,
        metadata, and dependencies. Subclasses should forward these to
        their sub-agent so per-user auth and framework-injected context
        (e.g. Slack ``action_token`` in ``metadata``) survive the hop.
        """
        raise NotImplementedError(f"{type(self).__name__} is read-only")

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        """Async variant of `update()`. Default: read-only."""
        raise NotImplementedError(f"{type(self).__name__} is read-only")

    @abstractmethod
    def status(self) -> Status: ...

    @abstractmethod
    async def astatus(self) -> Status: ...

    async def aclose(self) -> None:
        """Release any resources this provider is holding. Default: no-op.

        Override in subclasses that keep long-lived state — an open MCP
        session, a watched inbox, a webhook subscription. Callers tearing
        down multiple providers should await ``aclose()`` with
        ``asyncio.gather(return_exceptions=True)`` so one stuck teardown
        can't block the others. Must be safe to call even if the provider
        was never fully initialized (e.g. lazy session never connected).
        """
        return None

    async def asetup(self) -> None:
        """Setup any resources the provider needs. Default: no-op.

        Override in subclasses that need async initialization —
        connecting to an MCP session, opening a watch stream, priming a
        cache. Paired with ``aclose()``. Must be idempotent (safe to
        call multiple times) and safe to call even if the provider
        was never fully initialized (e.g. lazy session never connected).
        """
        return None

    def instructions(self) -> str:
        """How a calling agent should use this provider.

        Mode-aware: branches on `self.mode`. Override in subclasses to
        give the agent substance — what queries work well, what shape
        answers come back in, what the underlying tools do.
        """
        if self.mode == ContextMode.tools:
            return f"`{self.name}`: use the underlying tools to explore this source."
        return f"`{self.name}`: call `{self.query_tool_name}(question)` to query this source."

    def get_tools(self) -> list:
        if self.mode == ContextMode.default:
            return self._default_tools()
        if self.mode == ContextMode.tools:
            return self._all_tools()
        return [self._query_tool()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_kwargs_for_sub_agent(self, run_context: RunContext | None) -> dict:
        """Extract kwargs to pass to a sub-agent ``arun()`` from the
        caller's RunContext.

        Propagates ``user_id``, ``session_id``, ``metadata``, and
        ``dependencies`` so per-user auth and framework-injected state
        (e.g. Slack's ``action_token`` in ``metadata``) reach the
        sub-agent. Message history and session_state stay with the
        outer agent — sub-agents run isolated.
        """
        if run_context is None:
            return {}
        kwargs: dict = {}
        for attr in ("user_id", "session_id", "metadata", "dependencies"):
            value = getattr(run_context, attr, None)
            if value:
                kwargs[attr] = value
        return kwargs

    def _default_tools(self) -> list:
        """What `mode=default` resolves to. Override in subclasses to set
        the provider's recommended exposure."""
        return [self._query_tool()]

    def _query_tool(self):
        provider = self

        @tool(name=self.query_tool_name)
        async def _query(question: str, run_context: RunContext | None = None) -> str:
            try:
                answer = await provider.aquery(question, run_context=run_context)
            except Exception as exc:
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            payload: dict = {"results": [asdict(r) for r in answer.results]}
            if answer.text is not None:
                payload["text"] = answer.text
            return json.dumps(payload)

        return _query

    def _update_tool(self):
        provider = self

        @tool(name=self.update_tool_name)
        async def _update(instruction: str, run_context: RunContext | None = None) -> str:
            try:
                answer = await provider.aupdate(instruction, run_context=run_context)
            except NotImplementedError:
                return json.dumps({"error": f"{provider.name} is read-only"})
            except Exception as exc:
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            payload: dict = {"results": [asdict(r) for r in answer.results]}
            if answer.text is not None:
                payload["text"] = answer.text
            return json.dumps(payload)

        return _update

    def _all_tools(self) -> list:
        return [self._query_tool()]


def _sanitize_id(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", raw.lower())
    return s.strip("_") or "context"

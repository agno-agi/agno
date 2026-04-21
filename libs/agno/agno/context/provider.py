"""
Context Providers
=================

A `ContextProvider` exposes a source of information — a folder of files,
the web, a database, an inbox — to an agent. Subclasses implement two methods:

- `query(question)` / `aquery(question)` — natural-language access; returns an `Answer`
- `status()` / `astatus()` — is the source reachable?

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
    kind: str = "file"
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
    ) -> None:
        self.id = id
        self.name = name or id
        self.mode = mode
        self.model = model
        self.query_tool_name = f"query_{_sanitize_id(id)}"

    @abstractmethod
    def query(self, question: str) -> Answer: ...

    @abstractmethod
    async def aquery(self, question: str) -> Answer: ...

    @abstractmethod
    def status(self) -> Status: ...

    @abstractmethod
    async def astatus(self) -> Status: ...

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

    def _default_tools(self) -> list:
        """What `mode=default` resolves to. Override in subclasses to set
        the provider's recommended exposure."""
        return [self._query_tool()]

    def _query_tool(self):
        provider = self

        @tool(name=self.query_tool_name)
        async def _query(question: str) -> str:
            try:
                answer = await provider.aquery(question)
            except Exception as exc:
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            payload: dict = {"results": [asdict(r) for r in answer.results]}
            if answer.text is not None:
                payload["text"] = answer.text
            return json.dumps(payload)

        return _query

    def _all_tools(self) -> list:
        return [self._query_tool()]


def _sanitize_id(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", raw.lower())
    return s.strip("_") or "context"

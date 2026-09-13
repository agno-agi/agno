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

`query_timeout` puts one wall-clock deadline on each `query_<id>` tool
call; see the `ContextProvider` docstring for its exact scope.

`instructions()` returns mode-aware usage guidance. The wiring layer
chooses how to surface it: inline in the system prompt, or via an
on-demand `learn_context(id)` meta-tool.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from agno.context.mode import ContextMode
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.tools import tool

if TYPE_CHECKING:
    from agno.agent import Agent
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
    """Base class for every context provider.

    ``query_timeout`` puts one wall-clock deadline (in seconds) on every
    ``query_<id>`` tool call, covering sub-agent acquisition and answer
    streaming; on expiry the tool yields an ``{"error": ...}`` chunk
    instead of hanging the calling agent's run. It bounds the tool
    surface only: programmatic ``query()`` / ``aquery()`` calls and the
    raw backend tools exposed by ``mode=ContextMode.tools`` stay
    unbounded. The write surface (``update_<id>``) is never bounded.
    Requires Python 3.11+ and a positive value when set.
    """

    def __init__(
        self,
        id: str,
        *,
        name: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        query_timeout: float | None = None,
        read: bool = True,
        write: bool = True,
        query_tool_name: str | None = None,
        update_tool_name: str | None = None,
        stream_sub_agent_events: bool = True,
    ) -> None:
        if not read and not write:
            raise ValueError(
                f"{type(self).__name__}: at least one of `read` or `write` must be True "
                "(a provider that exposes neither tool is meaningless)"
            )
        if query_timeout is not None:
            if sys.version_info < (3, 11):
                raise RuntimeError(
                    f"{type(self).__name__}: query_timeout requires Python 3.11+ (uses asyncio.timeout_at)"
                )
            if query_timeout <= 0:
                raise ValueError(f"{type(self).__name__}: query_timeout must be positive (got {query_timeout})")
        self.id = id
        self.name = name or id
        self.mode = mode
        self.model = model
        # Wall-clock budget (seconds) for each query-tool call; see the
        # class docstring for scope. None = unbounded.
        self.query_timeout = query_timeout
        # Per-direction toggles for the default surface. `read=False`
        # drops `query_<id>`; `write=False` drops `update_<id>`. Lets
        # callers expose an asymmetric surface (e.g. read-only voice
        # wiki, write-only event sink) without subclassing or
        # reaching for `mode=tools` / `mode=agent`.
        self.read = read
        self.write = write
        self.query_tool_name = query_tool_name or f"query_{_sanitize_id(id)}"
        self.update_tool_name = update_tool_name or f"update_{_sanitize_id(id)}"
        self.stream_sub_agent_events = stream_sub_agent_events

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

    async def _aget_query_agent(self, run_context: RunContext | None) -> "Agent | None":
        """Override to return the read sub-agent for streaming; None falls back to aquery()."""
        return None

    async def _aget_update_agent(self, run_context: RunContext | None) -> "Agent | None":
        """Override to return the write sub-agent for streaming; None falls back to aupdate()."""
        return None

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

    async def _arun_sub_agent(
        self,
        agent: "Agent",
        message: str,
        run_context: RunContext | None,
    ) -> Answer:
        """Run a sub-agent non-streaming and return the final Answer."""
        from agno.context._utils import answer_from_run

        kwargs = self._run_kwargs_for_sub_agent(run_context)
        output: RunOutput = await agent.arun(message, stream=False, **kwargs)
        return answer_from_run(output)

    async def _arun_sub_agent_stream(
        self,
        agent: "Agent",
        message: str,
        run_context: RunContext | None,
    ):
        """Stream events from a sub-agent, yield events only.

        Content is captured by models/base.py from RunContentEvent deltas.
        Don't yield RunOutput — that would duplicate content in the tool result.
        """
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        run_id = run_context.run_id if run_context else None

        async for event in agent.arun(
            message,
            stream=True,
            stream_events=True,
            yield_run_output=True,
            **kwargs,
        ):
            if isinstance(event, RunOutput):
                continue
            event.parent_run_id = getattr(event, "parent_run_id", None) or run_id
            yield event

    def _read_write_tools(self) -> list:
        """Helper for subclasses with both query + update tools.

        Honors the ``read`` / ``write`` flags so the same provider
        can be instantiated as read-only, write-only, or both. Use
        from a subclass's ``_default_tools`` when the provider's
        recommended surface is the two-tool split.
        """
        tools: list = []
        if self.read:
            tools.append(self._query_tool())
        if self.write:
            tools.append(self._update_tool())
        return tools

    def _query_tool(self):
        provider = self

        @tool(name=self.query_tool_name)
        async def _query(question: str, run_context: RunContext | None = None):
            chunks = provider._query_chunks(question, run_context)
            if provider.query_timeout is not None:
                chunks = provider._bounded_stream(chunks, provider.query_timeout)
            async for chunk in chunks:
                yield chunk

        return _query

    async def _query_chunks(self, question: str, run_context: RunContext | None):
        """The query pipeline: agent acquisition, aquery fallback, streaming."""
        try:
            agent = await self._aget_query_agent(run_context)
        except Exception as exc:
            yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            return

        if agent is None:
            try:
                answer = await self.aquery(question, run_context=run_context)
            except Exception as exc:
                yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})
                return
            yield json.dumps(serialize_answer(answer))
            return

        try:
            if self.stream_sub_agent_events:
                async for chunk in self._arun_sub_agent_stream(agent, question, run_context):
                    yield chunk
            else:
                answer = await self._arun_sub_agent(agent, question, run_context)
                yield json.dumps(serialize_answer(answer))
        except Exception as exc:
            yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    async def _bounded_stream(self, stream, timeout: float):
        """Yield ``stream``'s chunks under one wall-clock deadline.

        The deadline is computed once at entry, so it covers agent
        acquisition, a hanging ``aquery``, inter-chunk stalls, and
        steady streams whose total time exceeds the budget alike. Each
        ``anext`` runs under its own ``asyncio.timeout_at(deadline)``
        scope — a single scope held across a ``yield`` would cancel the
        consuming task while this generator is suspended. On expiry the
        underlying generator's cleanup is itself bounded so a hanging
        ``aclose`` cannot starve the timed-out error chunk.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            scope = asyncio.timeout_at(deadline)  # type: ignore[attr-defined]
            try:
                async with scope:
                    # The anext() builtin is 3.10+; the repo lints at py39.
                    chunk = await stream.__anext__()
            except StopAsyncIteration:
                return
            except TimeoutError:
                if not scope.expired():
                    # Raised by the provider itself, not our deadline.
                    raise
                try:
                    async with asyncio.timeout(1):  # type: ignore[attr-defined]
                        await stream.aclose()
                except Exception:
                    pass
                yield json.dumps({"error": f"{self.name} timed out after {timeout}s"})
                return
            yield chunk

    def _update_tool(self):
        provider = self

        @tool(name=self.update_tool_name)
        async def _update(instruction: str, run_context: RunContext | None = None):
            try:
                agent = await provider._aget_update_agent(run_context)
            except NotImplementedError:
                yield json.dumps({"error": f"{provider.name} is read-only"})
                return
            except Exception as exc:
                yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})
                return

            if agent is None:
                try:
                    answer = await provider.aupdate(instruction, run_context=run_context)
                except NotImplementedError:
                    yield json.dumps({"error": f"{provider.name} is read-only"})
                    return
                except Exception as exc:
                    yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})
                    return
                yield json.dumps(serialize_answer(answer))
                return

            try:
                if provider.stream_sub_agent_events:
                    async for chunk in provider._arun_sub_agent_stream(agent, instruction, run_context):
                        yield chunk
                else:
                    answer = await provider._arun_sub_agent(agent, instruction, run_context)
                    yield json.dumps(serialize_answer(answer))
            except Exception as exc:
                yield json.dumps({"error": f"{type(exc).__name__}: {exc}"})

        return _update

    def _all_tools(self) -> list:
        return [self._query_tool()]


def _sanitize_id(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", raw.lower())
    return s.strip("_") or "context"


def serialize_answer(answer: Answer) -> dict:
    """Build the JSON payload returned to the calling agent.

    Omit empty fields so the calling agent doesn't see filler. Today
    no provider populates ``Answer.results`` (the ``Document`` slot
    is reserved for providers that want to return structured hits
    alongside synthesized text); shipping ``"results": []`` on every
    call is dead weight in the prompt. ``text`` is omitted when None.
    If both are absent the payload is ``{}`` — honest "this tool
    returned nothing" signal to the calling agent.
    """
    payload: dict = {}
    if answer.results:
        payload["results"] = [asdict(r) for r in answer.results]
    if answer.text is not None:
        payload["text"] = answer.text
    return payload

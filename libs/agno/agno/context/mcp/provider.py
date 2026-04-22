"""
MCP Context Provider
====================

Wraps a single Model Context Protocol (MCP) server as a context
provider. One MCP server -> one provider -> one ``query_mcp_<slug>``
tool on the calling agent (via the sub-agent wrapper).

Why a sub-agent wrapper:

- Two MCP servers that each expose a ``search`` tool would collide if
  we flattened them onto the calling agent's tool list. The sub-agent
  namespace keeps each server's tool names isolated.
- Tool descriptions vary per server and change when the server
  updates. The sub-agent's instructions are built from
  ``list_tools()`` at connect time, so the calling agent never sees
  stale hand-written tool docs.
- A crashed server degrades gracefully: ``astatus()`` flips to
  ``ok=False`` without taking down the caller.

Lifecycle:

- ``asetup()`` connects to the server, bounded by ``timeout_seconds``.
  Safe to call multiple times. On failure it logs and clears partial
  state; the provider retries on the next call.
- ``aclose()`` releases the session on shutdown.

Callers should bracket usage with ``asetup`` / ``aclose`` (typically
from an app lifespan) so the ``mcp`` SDK's anyio cancel scopes exit
on the task that entered them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status, _sanitize_id
from agno.run import RunContext
from agno.tools.mcp import MCPTools
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.models.base import Model

Transport = Literal["stdio", "sse", "streamable-http"]


class MCPContextProvider(ContextProvider):
    """One MCP server wrapped as a context provider."""

    def __init__(
        self,
        server_name: str,
        *,
        transport: Transport,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        mcp_kwargs: dict[str, Any] | None = None,
        id: str | None = None,
        name: str | None = None,
        base_instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        resolved_id = id or f"mcp_{_sanitize_id(server_name)}"
        super().__init__(id=resolved_id, name=name or server_name, mode=mode, model=model)
        self.server_name = server_name
        self.transport: Transport = transport
        self.command = command
        self.args = list(args) if args else []
        self.url = url
        self.headers = dict(headers) if headers else None
        self.env = dict(env) if env else None
        self.timeout_seconds = timeout_seconds
        self.mcp_kwargs = dict(mcp_kwargs) if mcp_kwargs else {}
        self.base_instructions_text = (
            base_instructions if base_instructions is not None else DEFAULT_MCP_BASE_INSTRUCTIONS
        )

        self._validate_config()

        self._tools: MCPTools | None = None
        self._agent: Agent | None = None
        self._tool_descriptions: list[tuple[str, str, str]] = []

    # ------------------------------------------------------------------
    # Status + query
    # ------------------------------------------------------------------

    def status(self) -> Status:
        """Sync status — reports the last-known connection result.

        Does NOT attempt a fresh connect because ``_ensure_session`` is
        async. Callers that need a live probe should use ``astatus``.
        """
        if self._tools is not None and getattr(self._tools, "initialized", False):
            return Status(ok=True, detail=self._detail_ok())
        return Status(ok=True, detail=f"mcp: {self.server_name} (not yet connected)")

    async def astatus(self) -> Status:
        try:
            await self._ensure_session()
        except Exception as exc:
            return Status(ok=False, detail=f"mcp {self.server_name}: {type(exc).__name__}: {exc}")
        return Status(ok=True, detail=self._detail_ok())

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        raise NotImplementedError(
            "MCPContextProvider does not support sync query(); use aquery() (MCP sessions are async-only)."
        )

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        agent = await self._aensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await agent.arun(question, **kwargs))

    async def asetup(self) -> None:
        """Connect to the MCP server and load its tool catalog.

        Bounded by ``timeout_seconds``. Connects regardless of
        ``mode`` — ``mode=tools`` needs ``MCPTools.functions``
        populated before ``get_tools()`` is called, and the ``mcp``
        SDK's anyio cancel scopes must exit on the task that entered
        them (lifespan-task ownership avoids "cancel scope in a
        different task" errors on ``aclose``).

        On timeout or error: logs a warning and clears partial state.
        The provider retries on the next call.
        """
        try:
            await asyncio.wait_for(self._ensure_session(), timeout=self.timeout_seconds)
        except Exception as exc:
            self._tools = None
            self._tool_descriptions = []
            log_warning(
                f"MCPContextProvider[{self.id}]: setup failed — "
                f"{type(exc).__name__}: {exc}. Provider will retry on next call."
            )

    async def aclose(self) -> None:
        """Close the MCP session and drop cached state. Safe to call
        even if the session never connected.
        """
        tools = self._tools
        self._tools = None
        self._agent = None
        self._tool_descriptions = []
        if tools is not None:
            try:
                await tools.close()
            except Exception as exc:
                log_warning(f"MCPContextProvider[{self.id}]: close() raised {type(exc).__name__}: {exc}")

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}` (MCP): call the server's tools directly. "
                "mode=tools only works in isolation — tool names vary by server."
            )
        return (
            f"`{self.name}` (MCP): call `{self.query_tool_name}(question)` to query "
            f"this MCP server. Routes through a sub-agent that picks among the "
            f"server's exposed tools."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        # Always wrap behind a sub-agent — two MCP servers with a shared
        # tool name (e.g. `search`) would otherwise collide on the caller.
        return [self._query_tool()]

    def _all_tools(self) -> list:
        tools = self._tools
        if tools is None:
            # Return an unconnected toolkit — caller is expected to have
            # already wired asetup() / aclose() into their lifecycle.
            tools = self._build_tools_instance()
            self._tools = tools
        return [tools]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"MCPContextProvider[{self.id}]: transport=stdio requires `command`")
        elif self.transport in ("sse", "streamable-http"):
            if not self.url:
                raise ValueError(f"MCPContextProvider[{self.id}]: transport={self.transport} requires `url`")
        else:
            raise ValueError(f"MCPContextProvider[{self.id}]: unknown transport {self.transport!r}")

    def _detail_ok(self) -> str:
        n = len(self._tool_descriptions)
        return f"mcp: {self.server_name} ({n} tool{'s' if n != 1 else ''})"

    def _build_tools_instance(self) -> MCPTools:
        """Construct an unconnected ``MCPTools`` for this server.

        The ``command``/``args`` split in the provider interface is
        flattened into a single command string here because
        ``MCPTools(command=...)`` shlex-splits internally.
        """
        from shlex import join as shlex_join

        kwargs: dict[str, Any] = {"transport": self.transport, "timeout_seconds": self.timeout_seconds}
        if self.transport == "stdio":
            command_parts = [self.command or ""] + self.args
            kwargs["command"] = shlex_join([p for p in command_parts if p])
            if self.env:
                kwargs["env"] = self.env
        else:
            kwargs["url"] = self.url
            if self.headers:
                # MCPTools doesn't accept `headers` as a direct kwarg;
                # pass via server_params for http/sse transports.
                from agno.tools.mcp.params import (
                    SSEClientParams,
                    StreamableHTTPClientParams,
                )

                if self.transport == "sse":
                    kwargs["server_params"] = SSEClientParams(url=self.url or "", headers=self.headers)
                else:
                    kwargs["server_params"] = StreamableHTTPClientParams(url=self.url or "", headers=self.headers)

        # Escape hatch: anything accepted by ``agno.tools.mcp.MCPTools``.
        # User-provided keys override anything the provider set.
        kwargs.update(self.mcp_kwargs)

        return MCPTools(**kwargs)

    async def _ensure_session(self) -> MCPTools:
        """Lazily connect and cache the tools instance. Idempotent."""
        if self._tools is not None and getattr(self._tools, "initialized", False):
            return self._tools
        if self._tools is None:
            self._tools = self._build_tools_instance()
        try:
            await self._tools._connect()
        except Exception:
            # Reset so the next attempt gets a fresh toolkit — a failed
            # connect can leave MCPTools in a partially-initialized state.
            self._tools = None
            self._tool_descriptions = []
            raise
        self._tool_descriptions = _describe_tools(self._tools)
        return self._tools

    async def _aensure_agent(self) -> Agent:
        """Lazy-build the sub-agent AFTER the MCP session is connected
        so the tool descriptions reflect what the server actually
        exposes.
        """
        await self._ensure_session()
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            model=self.model,
            instructions=self._agent_instructions(),
            tools=[self._tools] if self._tools is not None else [],
            markdown=True,
        )

    def _agent_instructions(self) -> str:
        """Build instructions dynamically from the server's tool list."""
        if not self._tool_descriptions:
            tool_block = "(no tools discovered — the server may be misconfigured)"
        else:
            tool_block = "\n".join(
                f"- `{name}`: {desc}\n  Arguments: {args}" for name, desc, args in self._tool_descriptions
            )
        return self.base_instructions_text.replace("{server_name}", self.server_name).replace(
            "{tool_block}", tool_block
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _describe_tools(tools: MCPTools) -> list[tuple[str, str, str]]:
    """Return ``(name, description, arguments)`` tuples for instructions."""
    out: list[tuple[str, str, str]] = []
    for fn_name, fn in getattr(tools, "functions", {}).items():
        desc = (getattr(fn, "description", None) or "").strip() or "(no description)"
        params = getattr(fn, "parameters", None) or {}
        props = params.get("properties", {}) if isinstance(params, dict) else {}
        required = set(params.get("required", []) if isinstance(params, dict) else [])
        if not isinstance(props, dict) or not props:
            args_str = "(none)"
        else:
            args_str = ", ".join(
                f"{pname}: {_schema_type(pschema)}{'' if pname in required else '?'}"
                for pname, pschema in props.items()
            )
        out.append((fn_name, desc, args_str))
    return out


def _schema_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "any"
    t = schema.get("type")
    if isinstance(t, list):
        return "|".join(str(x) for x in t)
    return str(t) if t else "any"


DEFAULT_MCP_BASE_INSTRUCTIONS = """\
You answer questions by calling tools exposed by the `{server_name}` MCP server.

## Tools available

{tool_block}

## Workflow

1. **Match tool to intent.** Pick the tool whose description fits the
   user's question. If no tool clearly matches, say so plainly —
   don't guess at tools that aren't on the list.
2. **Call with explicit, well-typed arguments.** The argument types
   above are from the server's declared schema. Required arguments
   are unmarked; optional ones end with `?`.
3. **Return tool output verbatim where possible.** MCP servers
   usually structure responses intentionally — don't paraphrase IDs,
   dates, URLs, or quoted text.
4. **Propagate errors as-is.** If a tool call returns an error, report
   the error text — don't fabricate a fallback from training knowledge.
5. **Read-only by default.** Don't call tools whose description
   indicates a write (create, update, delete, send, post) unless the
   user explicitly asked for that action.
"""

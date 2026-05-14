"""ParallelMCPBackend — keyless (or keyed) web search via Parallel's MCP server.

Exposes Parallel's `web_search` + `web_fetch` tools to the calling
agent. The default endpoint is keyless; passing `api_key` (or setting
`PARALLEL_API_KEY`) authenticates via Bearer token and raises the
rate ceiling.

Two endpoints are supported:
- `search.parallel.ai/mcp` (default): allows anonymous use, Bearer token
  optional. Good for prototyping and single-user dev.
- `search.parallel.ai/mcp-oauth` (`authenticated=True`): authenticated-only,
  rejects anonymous requests with 401. Use for org-wide deployments, ZDR
  contexts, or MCP clients that negotiate auth via OAuth2.

Pairs with `ParallelBackend` (direct SDK) — the two are not equivalent:
the SDK exposes `web_search` + `web_extract`, whereas the MCP server
exposes `web_search` + `web_fetch` (token-efficient markdown). Pick
MCP when you want the compressed markdown output, SDK when you need
the raw extraction payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import wraps
from os import getenv
from typing import Any, Optional

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.exceptions import StopAgentRun
from agno.utils.log import log_info, log_warning

# `agno/utils/mcp.py` formats every MCP tool failure — protocol errors
# (402, 429, ...), timeouts, transport exceptions — with one of these
# prefixes. Matching them deterministically catches *any* unhealthy call
# without keyword whack-a-mole on the embedded message.
_MCP_ERROR_PREFIXES = (
    "Error from MCP tool",
    "Error:",
)

_BASE_URL = "https://search.parallel.ai/mcp"
_OAUTH_BASE_URL = "https://search.parallel.ai/mcp-oauth"
_DEFAULT_TOOLS: Sequence[str] = ("web_search", "web_fetch")


class ParallelMCPBackend(ContextBackend):
    """Backend for `WebContextProvider` that speaks to Parallel's MCP server."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        authenticated: bool = False,
        timeout_seconds: int = 60,
        include_tools: Sequence[str] | None = _DEFAULT_TOOLS,
        exclude_tools: Sequence[str] | None = None,
        tool_name_prefix: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else (getenv("PARALLEL_API_KEY", "") or None)
        self.url = _OAUTH_BASE_URL if authenticated else _BASE_URL
        self.include_tools = list(include_tools) if include_tools is not None else None
        self.exclude_tools = list(exclude_tools) if exclude_tools is not None else None
        self.tool_name_prefix = tool_name_prefix
        # /mcp-oauth rejects anonymous requests with 401 (unlike /mcp), so
        # the endpoint is unusable without a key — fail fast instead of
        # surfacing a runtime 401 during asetup().
        if self.url == _OAUTH_BASE_URL and not self.api_key:
            raise ValueError("authenticated=True requires api_key (or PARALLEL_API_KEY env var).")
        # web_fetch returns server-compressed markdown for long pages and
        # regularly exceeds MCPTools' 10s default.
        self.timeout_seconds = timeout_seconds
        self._mcp_tools: Any = None

    def status(self) -> Status:
        endpoint = self.url.rsplit("/", 1)[-1]
        return Status(ok=True, detail=f"search.parallel.ai/{endpoint} ({'keyed' if self.api_key else 'keyless'})")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def get_tools(self) -> list:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> Any:
        from datetime import timedelta

        from agno.tools.mcp import MCPTools
        from agno.tools.mcp.params import StreamableHTTPClientParams

        headers: dict[str, Any] | None = None
        if self.api_key:
            headers = {"Authorization": f"Bearer {self.api_key}"}

        server_params = StreamableHTTPClientParams(
            url=self.url,
            headers=headers,
            timeout=timedelta(seconds=self.timeout_seconds),
        )
        mcp_tools = MCPTools(
            server_params=server_params,
            transport="streamable-http",
            include_tools=self.include_tools,
            exclude_tools=self.exclude_tools,
            tool_name_prefix=self.tool_name_prefix,
            timeout_seconds=self.timeout_seconds,
        )
        # The agent loop may initialize tools via either `_connect()` (our
        # `asetup` path) or `initialize()` (the agent's own lazy path).
        # Both flow through `build_tools()`, so wrap *that* to guarantee
        # the guard installs no matter which entrypoint runs first.
        self._wrap_build_tools(mcp_tools)
        return mcp_tools

    @staticmethod
    def _wrap_build_tools(mcp_tools: Any) -> None:
        """Wrap `MCPTools.build_tools` so the degraded-backend guard is
        re-installed every time the tool list is built or refreshed."""
        original_build_tools = mcp_tools.build_tools

        @wraps(original_build_tools)
        async def build_tools_with_guard(*args: Any, **kwargs: Any) -> Any:
            result = await original_build_tools(*args, **kwargs)
            ParallelMCPBackend._install_degraded_backend_guard(mcp_tools)
            return result

        mcp_tools.build_tools = build_tools_with_guard

    async def asetup(self) -> None:
        """Connect to the Parallel MCP server.

        On failure, logs a warning; the web backend will be
        unavailable until the next restart.
        """
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        if getattr(self._mcp_tools, "initialized", False):
            return
        log_info(f"ParallelMCPBackend: connecting to {self.url} ({'keyed' if self.api_key else 'keyless'})")
        try:
            # The guard is installed via `_wrap_build_tools` (called from
            # `_build_tools`), so it's already wired in whether `_connect`
            # or the agent loop's lazy `initialize()` runs first.
            await self._mcp_tools._connect()
        except Exception as exc:
            log_warning(f"ParallelMCPBackend setup failed — {type(exc).__name__}: {exc}.")
            self._mcp_tools = None

    @staticmethod
    def _install_degraded_backend_guard(mcp_tools: Any) -> None:
        """Wrap each MCP function's entrypoint so *any* tool-call failure —
        protocol error (402/429/...), timeout, transport exception — halts
        the sub-agent at the tool boundary via `StopAgentRun`. Without this,
        the LLM sees an opaque error string and either retries blindly or
        improvises an answer from training data."""

        for fn in mcp_tools.functions.values():
            original = fn.entrypoint
            if original is None or getattr(original, "_parallel_guard_installed", False):
                continue

            @wraps(original)
            async def guarded(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                result = await _original(*args, **kwargs)
                content = getattr(result, "content", "") or ""
                if isinstance(content, str) and content.startswith(_MCP_ERROR_PREFIXES):
                    detail = content.strip()
                    log_warning(f"ParallelMCPBackend: tool call failed — {detail[:200]}")
                    message = f"Web backend unavailable: {detail}"
                    raise StopAgentRun(message, agent_message=message)
                return result

            guarded._parallel_guard_installed = True  # type: ignore[attr-defined]
            fn.entrypoint = guarded

    async def aclose(self) -> None:
        """Close the MCP session and clear the cached tool handle."""
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            await tools.close()
        except Exception as exc:
            log_warning(f"ParallelMCPBackend close raised {type(exc).__name__}: {exc}")

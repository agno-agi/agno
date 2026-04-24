"""ParallelMCPBackend — keyless (or keyed) web search via Parallel's MCP server.

Exposes Parallel's `web_search` + `web_fetch` tools to the calling
agent. The default endpoint is keyless; passing `api_key` (or setting
`PARALLEL_API_KEY`) authenticates via Bearer token and raises the
rate ceiling.

Two endpoints are supported:
- `search.parallel.ai/mcp` (default): allows anonymous use, Bearer token
  optional. Good for prototyping and single-user dev.
- `search.parallel.ai/mcp-oauth` (`use_oauth_endpoint=True`): authenticated-only,
  rejects anonymous requests with 401. Use for org-wide deployments, ZDR
  contexts, or MCP clients that negotiate auth via OAuth2.

Pairs with `ParallelBackend` (direct SDK) — the two are not equivalent:
the SDK exposes `web_search` + `web_extract`, whereas the MCP server
exposes `web_search` + `web_fetch` (token-efficient markdown). Pick
MCP when you want the compressed markdown output, SDK when you need
the raw extraction payload.
"""

from __future__ import annotations

from os import getenv
from typing import Any

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_warning

_BASE_URL = "https://search.parallel.ai/mcp"
_OAUTH_BASE_URL = "https://search.parallel.ai/mcp-oauth"
_TOOLS = ("web_search", "web_fetch")


class ParallelMCPBackend(ContextBackend):
    """Backend for `WebContextProvider` that speaks to Parallel's MCP server."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        use_oauth_endpoint: bool = False,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key if api_key is not None else (getenv("PARALLEL_API_KEY", "") or None)
        # /mcp-oauth rejects anonymous requests with 401 (unlike /mcp), so
        # the endpoint is unusable without a key — fail fast instead of
        # surfacing a runtime 401 during asetup().
        if use_oauth_endpoint and not self.api_key:
            raise ValueError("use_oauth_endpoint=True requires api_key (or PARALLEL_API_KEY env var).")
        self.use_oauth_endpoint = use_oauth_endpoint
        self.url = _OAUTH_BASE_URL if self.use_oauth_endpoint else _BASE_URL
        # web_fetch returns server-compressed markdown for long pages and
        # regularly exceeds MCPTools' 10s default.
        self.timeout_seconds = timeout_seconds
        self._mcp_tools: Any = None

    def status(self) -> Status:
        endpoint = self.url.rsplit("/", 1)[-1]
        return Status(ok=True, detail=f"search.parallel.ai/{endpoint} ({'keyed' if self.api_key else 'keyless'})")

    async def astatus(self) -> Status:
        return self.status()

    def get_tools(self) -> list:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> Any:
        from agno.tools.mcp import MCPTools
        from agno.tools.mcp.params import StreamableHTTPClientParams

        headers: dict[str, Any] | None = None
        if self.api_key:
            headers = {"Authorization": f"Bearer {self.api_key}"}

        server_params = StreamableHTTPClientParams(url=self.url, headers=headers)
        return MCPTools(
            server_params=server_params,
            transport="streamable-http",
            include_tools=list(_TOOLS),
            timeout_seconds=self.timeout_seconds,
        )

    async def asetup(self) -> None:
        """Connect to the Parallel MCP server.

        On failure, logs a warning; the web backend will be
        unavailable until the next restart.
        """
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        if getattr(self._mcp_tools, "initialized", False):
            return
        try:
            await self._mcp_tools._connect()
        except Exception as exc:
            log_warning(f"ParallelMCPBackend setup failed — {type(exc).__name__}: {exc}.")
            self._mcp_tools = None

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

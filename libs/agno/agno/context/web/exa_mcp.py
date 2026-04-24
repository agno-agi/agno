"""ExaMCPBackend — keyless (or keyed) web search via Exa's public MCP server.

Exposes Exa's `web_search_exa` + `web_fetch_exa` tools to the calling
agent. The default endpoint is keyless; passing `api_key` (or setting
`EXA_API_KEY`) raises the rate ceiling.

Fallback option — prefer `ExaBackend` (direct SDK) when `EXA_API_KEY`
is set. MCP adds connection-setup overhead that isn't worth it when
the SDK path is available.
"""

from __future__ import annotations

from collections.abc import Sequence
from os import getenv
from typing import Any

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_warning

_BASE_URL = "https://mcp.exa.ai/mcp"
_DEFAULT_TOOLS: Sequence[str] = ("web_search_exa", "web_fetch_exa")


class ExaMCPBackend(ContextBackend):
    """Backend for `WebContextProvider` that speaks to Exa's MCP server."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: int = 60,
        include_tools: Sequence[str] | None = _DEFAULT_TOOLS,
        exclude_tools: Sequence[str] | None = None,
        tool_name_prefix: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else (getenv("EXA_API_KEY", "") or None)
        self.timeout_seconds = timeout_seconds
        self.include_tools = list(include_tools) if include_tools is not None else None
        self.exclude_tools = list(exclude_tools) if exclude_tools is not None else None
        self.tool_name_prefix = tool_name_prefix
        # Build URL with tool filter query param
        tools_param = ",".join(self.include_tools) if self.include_tools else ""
        if self.api_key:
            self.url = f"{_BASE_URL}?exaApiKey={self.api_key}&tools={tools_param}"
        else:
            self.url = f"{_BASE_URL}?tools={tools_param}"
        self._mcp_tools: Any = None

    def status(self) -> Status:
        return Status(ok=True, detail=f"mcp.exa.ai ({'keyed' if self.api_key else 'keyless'})")

    async def astatus(self) -> Status:
        return self.status()

    def get_tools(self) -> list:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> Any:
        from datetime import timedelta

        from agno.tools.mcp import MCPTools
        from agno.tools.mcp.params import StreamableHTTPClientParams

        server_params = StreamableHTTPClientParams(
            url=self.url,
            timeout=timedelta(seconds=self.timeout_seconds),
        )
        return MCPTools(
            server_params=server_params,
            transport="streamable-http",
            exclude_tools=self.exclude_tools,
            tool_name_prefix=self.tool_name_prefix,
            timeout_seconds=self.timeout_seconds,
        )

    async def asetup(self) -> None:
        """Connect to the Exa MCP server.

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
            log_warning(f"ExaMCPBackend setup failed — {type(exc).__name__}: {exc}.")
            self._mcp_tools = None

    async def aclose(self) -> None:
        """Close the MCP session and drop cached state."""
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            await tools.close()
        except Exception as exc:
            log_warning(f"ExaMCPBackend close raised {type(exc).__name__}: {exc}")

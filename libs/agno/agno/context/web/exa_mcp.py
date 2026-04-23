"""ExaMCPBackend — keyless (or keyed) web search via Exa's public MCP server.

Exposes Exa's `web_search_exa` + `web_fetch_exa` tools to the calling
agent. The default endpoint is keyless; passing `api_key` (or setting
`EXA_API_KEY`) raises the rate ceiling.

Fallback option — prefer `ExaBackend` (direct SDK) when `EXA_API_KEY`
is set. MCP adds connection-setup overhead that isn't worth it when
the SDK path is available.
"""

from __future__ import annotations

from os import getenv
from typing import Any

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_warning

_BASE_URL = "https://mcp.exa.ai/mcp"
_TOOLS = "web_search_exa,web_fetch_exa"


class ExaMCPBackend(ContextBackend):
    """Backend for `WebContextProvider` that speaks to Exa's MCP server."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else (getenv("EXA_API_KEY", "") or None)
        if self.api_key:
            self.url = f"{_BASE_URL}?exaApiKey={self.api_key}&tools={_TOOLS}"
        else:
            self.url = f"{_BASE_URL}?tools={_TOOLS}"
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
        from agno.tools.mcp import MCPTools

        return MCPTools(url=self.url, transport="streamable-http")

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

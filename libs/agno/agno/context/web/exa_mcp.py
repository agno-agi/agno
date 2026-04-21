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
            from agno.tools.mcp import MCPTools

            self._mcp_tools = MCPTools(url=self.url, transport="streamable-http")
        return [self._mcp_tools]

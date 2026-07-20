"""PlaywrightMCPBackend — browser automation via Playwright's MCP server.

Runs `npx @playwright/mcp@latest` as a subprocess and exposes browser
tools (navigate, snapshot, screenshot, click, type) to the calling agent.

Requires Node.js 18+ (npx downloads the package on first run).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.tools import Toolkit
    from agno.tools.mcp import MCPTools


class PlaywrightMCPBackend(ContextBackend):
    """Backend for `BrowserContextProvider` that runs Playwright's MCP server."""

    def __init__(
        self,
        *,
        headless: bool = True,
        include_tools: list[str] | None = None,
        exclude_tools: list[str] | None = None,
        tool_name_prefix: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.headless = headless
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.tool_name_prefix = tool_name_prefix
        self.timeout_seconds = timeout_seconds
        self._mcp_tools: MCPTools | None = None

    def status(self) -> Status:
        if self._mcp_tools is not None and getattr(self._mcp_tools, "initialized", False):
            return Status(ok=True, detail="playwright-mcp")
        return Status(ok=True, detail="playwright-mcp (not yet connected)")

    async def astatus(self) -> Status:
        try:
            await self._ensure_session()
        except Exception as exc:
            return Status(ok=False, detail=f"playwright-mcp: {type(exc).__name__}: {exc}")
        return Status(ok=True, detail="playwright-mcp")

    def get_tools(self) -> list[Toolkit]:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> MCPTools:
        from mcp import StdioServerParameters

        from agno.tools.mcp import MCPTools

        cmd_args = ["@playwright/mcp@latest"]
        if self.headless:
            cmd_args.append("--headless")

        return MCPTools(
            server_params=StdioServerParameters(command="npx", args=cmd_args),
            transport="stdio",
            include_tools=self.include_tools,
            exclude_tools=self.exclude_tools,
            tool_name_prefix=self.tool_name_prefix,
            timeout_seconds=self.timeout_seconds,
        )

    async def _ensure_session(self) -> MCPTools:
        if self._mcp_tools is not None and getattr(self._mcp_tools, "initialized", False):
            return self._mcp_tools
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        try:
            await self._mcp_tools._connect()
        except Exception:
            self._mcp_tools = None
            raise
        return self._mcp_tools

    async def asetup(self) -> None:
        try:
            await self._ensure_session()
        except Exception as exc:
            log_warning(f"PlaywrightMCPBackend setup failed: {type(exc).__name__}: {exc}")

    async def aclose(self) -> None:
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            await tools.close()
        except Exception as exc:
            log_warning(f"PlaywrightMCPBackend close raised {type(exc).__name__}: {exc}")

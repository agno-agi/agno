"""PlaywrightMCPBackend — browser automation via Playwright's official MCP server.

Exposes Playwright's browser tools via the accessibility tree, which is more
token-efficient than vision-based approaches (~1/4 the tokens). Element refs
are deterministic within a page snapshot.

Requires Node.js 18+ and `@playwright/mcp` installed globally or via npx.

The server runs as a subprocess via stdio transport. Each backend instance
manages its own browser session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_info, log_warning


class PlaywrightMCPBackend(ContextBackend):
    """Backend for `BrowserContextProvider` using Playwright's MCP server.

    Args:
        command: Command to start the MCP server. Defaults to npx.
        args: Arguments for the command. Defaults to ["@playwright/mcp@latest"].
        headless: Run browser in headless mode. Defaults to True.
        include_tools: Allowlist of tool names to expose. None = all tools.
        exclude_tools: Denylist of tool names to hide.
        timeout_seconds: Timeout for MCP operations.
    """

    def __init__(
        self,
        *,
        command: str = "npx",
        args: Sequence[str] | None = None,
        headless: bool = True,
        include_tools: Sequence[str] | None = None,
        exclude_tools: Sequence[str] | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.command = command
        self.args = list(args) if args is not None else ["@playwright/mcp@latest"]
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.include_tools = list(include_tools) if include_tools is not None else None
        self.exclude_tools = list(exclude_tools) if exclude_tools is not None else None
        self._mcp_tools: Any = None

    def status(self) -> Status:
        if self._mcp_tools is None:
            return Status(ok=True, detail="playwright-mcp (not connected)")
        if getattr(self._mcp_tools, "initialized", False):
            return Status(ok=True, detail="playwright-mcp (connected)")
        return Status(ok=True, detail="playwright-mcp (connecting)")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def get_tools(self) -> list:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> Any:
        from mcp import StdioServerParameters

        from agno.tools.mcp import MCPTools

        # Build command args with headless flag
        cmd_args = list(self.args)
        if self.headless and "--headless" not in cmd_args:
            cmd_args.append("--headless")

        server_params = StdioServerParameters(
            command=self.command,
            args=cmd_args,
        )

        return MCPTools(
            server_params=server_params,
            transport="stdio",
            include_tools=self.include_tools,
            exclude_tools=self.exclude_tools,
            timeout_seconds=self.timeout_seconds,
        )

    async def asetup(self) -> None:
        """Start the Playwright MCP server and connect.

        On failure, logs a warning; the browser backend will be
        unavailable until the next restart.
        """
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        if getattr(self._mcp_tools, "initialized", False):
            return
        log_info(f"PlaywrightMCPBackend: starting {self.command} {' '.join(self.args)}")
        try:
            await self._mcp_tools._connect()
        except Exception as exc:
            log_warning(f"PlaywrightMCPBackend setup failed — {type(exc).__name__}: {exc}")
            self._mcp_tools = None

    async def aclose(self) -> None:
        """Stop the MCP server and clear the cached tool handle."""
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            await tools.close()
        except Exception as exc:
            log_warning(f"PlaywrightMCPBackend close raised {type(exc).__name__}: {exc}")

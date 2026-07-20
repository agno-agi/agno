"""BrowserbaseMCPBackend — cloud browser via Browserbase MCP + Stagehand.

Requires: Node.js 18+, BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, GEMINI_API_KEY
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.tools import Toolkit


class BrowserbaseMCPBackend(ContextBackend):
    """Browserbase MCP backend with Stagehand semantic actions (act, extract)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        project_id: str | None = None,
        model_api_key: str | None = None,
        include_tools: list[str] | None = None,
        exclude_tools: list[str] | None = None,
        tool_name_prefix: str | None = "browser",
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key or getenv("BROWSERBASE_API_KEY")
        self.project_id = project_id or getenv("BROWSERBASE_PROJECT_ID")
        self.model_api_key = model_api_key or getenv("GEMINI_API_KEY")
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.tool_name_prefix = tool_name_prefix
        self.timeout_seconds = timeout_seconds
        self._mcp_tools: Toolkit | None = None

    def status(self) -> Status:
        missing = []
        if not self.api_key:
            missing.append("BROWSERBASE_API_KEY")
        if not self.project_id:
            missing.append("BROWSERBASE_PROJECT_ID")
        if missing:
            return Status(ok=False, detail=f"browserbase-mcp: missing {', '.join(missing)}")
        if self._mcp_tools is not None and getattr(self._mcp_tools, "initialized", False):
            return Status(ok=True, detail="browserbase-mcp")
        return Status(ok=True, detail="browserbase-mcp (not yet connected)")

    async def astatus(self) -> Status:
        try:
            await self._ensure_session()
        except Exception as exc:
            return Status(ok=False, detail=f"browserbase-mcp: {type(exc).__name__}: {exc}")
        return Status(ok=True, detail="browserbase-mcp")

    def get_tools(self) -> list[Toolkit]:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _build_tools(self) -> Toolkit:
        from mcp import StdioServerParameters

        from agno.tools.mcp import MCPTools

        env: dict[str, str] = {}
        if self.api_key:
            env["BROWSERBASE_API_KEY"] = self.api_key
        if self.project_id:
            env["BROWSERBASE_PROJECT_ID"] = self.project_id
        if self.model_api_key:
            env["GEMINI_API_KEY"] = self.model_api_key

        return MCPTools(
            server_params=StdioServerParameters(
                command="npx",
                args=["@browserbasehq/mcp-server-browserbase"],
                env=env if env else None,
            ),
            transport="stdio",
            include_tools=self.include_tools,
            exclude_tools=self.exclude_tools,
            tool_name_prefix=self.tool_name_prefix,
            timeout_seconds=self.timeout_seconds,
        )

    async def _ensure_session(self) -> Toolkit:
        if self._mcp_tools is not None and getattr(self._mcp_tools, "initialized", False):
            return self._mcp_tools
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        try:
            await self._mcp_tools._connect()  # type: ignore[attr-defined]
        except Exception:
            self._mcp_tools = None
            raise
        return self._mcp_tools

    async def asetup(self) -> None:
        try:
            await self._ensure_session()
        except Exception as exc:
            log_warning(f"BrowserbaseMCPBackend setup failed: {type(exc).__name__}: {exc}")

    async def aclose(self) -> None:
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            tools.close()  # type: ignore[func-returns-value]
        except Exception as exc:
            log_warning(f"BrowserbaseMCPBackend close raised {type(exc).__name__}: {exc}")

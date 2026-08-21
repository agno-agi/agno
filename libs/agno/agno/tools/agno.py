from os import getenv
from typing import Any, List, Optional

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    EmptyResult,
    ErrorData,
    InitializeResult,
    ListToolsResult,
)

from agno.tools.mcp import MCPTools
from agno.utils.mcp import build_mcp_auth_headers

DEFAULT_AGNO_TOOLS_URL = "http://localhost:8787/mcp"

# Why AgnoTools should be stateless:
# Each run uses a short-lived user/organization token.
# Toolkits are created for fresh per-request Agent/Team copies.
# Concurrent users must never share authentication or session context.
# Cloudflare Workers can handle consecutive calls on different instances.
# No server affinity or persistent connection is required.
# It avoids MCP AnyIO connections crossing Starlette streaming tasks—the crash we encountered.
# Cleanup, cancellation, and token expiry are simpler.

class _StatelessGatewaySession:
    """Minimal MCP session for the Gateway's one-request/one-response transport."""

    def __init__(self, url: str, api_key: Optional[str], timeout_seconds: int = 10):
        self.url = url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._request_id = 0

    async def _request(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._request_id += 1
        resolved_api_key = self.api_key or getenv("AGNO_API_KEY")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if resolved_api_key:
            headers.update(build_mcp_auth_headers(resolved_api_key))

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params or {},
                },
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()[:300]
            message = f"Agno Gateway MCP {method} failed with HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Invalid response from the Agno Gateway MCP endpoint")
        if payload.get("error") is not None:
            raise McpError(ErrorData.model_validate(payload["error"]))

        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("Missing MCP result from the Agno Gateway")
        return result

    async def initialize(self) -> InitializeResult:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agno", "version": "1"},
            },
        )
        return InitializeResult.model_validate(result)

    async def send_ping(self) -> EmptyResult:
        return EmptyResult.model_validate(await self._request("ping"))

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult.model_validate(await self._request("tools/list"))

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> CallToolResult:
        result = await self._request("tools/call", {"name": name, "arguments": arguments or {}})
        return CallToolResult.model_validate(result)


class AgnoTools(MCPTools):
    """Access hosted Agno tools through the stateless Agno Gateway MCP endpoint."""

    def __init__(
        self,
        *,
        include_tools: Optional[List[str]] = None,
        api_key: Optional[str] = None,
    ):
        url = getenv("AGNO_GATEWAY_MCP_URL") or DEFAULT_AGNO_TOOLS_URL
        super().__init__(
            name="agno_tools",
            url=url,
            transport="streamable-http",
            session=_StatelessGatewaySession(url=url, api_key=api_key),  # type: ignore[arg-type]
            include_tools=include_tools,
            api_key=api_key,
        )

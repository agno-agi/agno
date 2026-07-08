"""Minimal MCP streamable-HTTP client, used only to verify connections.

Speaks just enough JSON-RPC over streamable HTTP (initialize -> notifications/initialized
-> tools/list) to prove that a written client config would actually work. Implemented on
plain httpx so the CLI does not depend on the mcp package.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from agnoctl import __version__
from agnoctl.http import build_client

PROTOCOL_VERSION = "2025-03-26"

SESSION_HEADER = "mcp-session-id"


@dataclass
class MCPVerifyResult:
    ok: bool
    tools: List[str] = field(default_factory=list)
    status_code: Optional[int] = None
    error: Optional[str] = None

    def public_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "tools": len(self.tools), "status_code": self.status_code, "error": self.error}


def _parse_jsonrpc_body(response: httpx.Response) -> Optional[Dict[str, Any]]:
    """Extract the first JSON-RPC message from a JSON or SSE response body."""
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def verify_mcp(mcp_url: str, token: Optional[str] = None, timeout: float = 15.0) -> MCPVerifyResult:
    """Handshake with an MCP streamable-HTTP endpoint and list its tools.

    Never raises: connection problems and malformed payloads come back as a failed
    MCPVerifyResult so callers can report per-client outcomes.
    """
    try:
        return _verify_mcp(mcp_url, token, timeout)
    except Exception as e:  # never-raises contract
        return MCPVerifyResult(ok=False, error="MCP verification failed: " + str(e))


def _verify_mcp(mcp_url: str, token: Optional[str], timeout: float) -> MCPVerifyResult:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = "Bearer " + token

    try:
        with build_client(timeout=timeout) as client:
            init_response = client.post(
                mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "agnoctl", "version": __version__},
                    },
                },
            )
            if init_response.status_code in (401, 403):
                return MCPVerifyResult(
                    ok=False,
                    status_code=init_response.status_code,
                    error="The MCP endpoint rejected the credential (HTTP " + str(init_response.status_code) + ").",
                )
            if init_response.status_code >= 400:
                return MCPVerifyResult(
                    ok=False,
                    status_code=init_response.status_code,
                    error="MCP initialize failed with HTTP " + str(init_response.status_code) + ".",
                )
            init_message = _parse_jsonrpc_body(init_response)
            if init_message is None or "result" not in init_message:
                return MCPVerifyResult(
                    ok=False,
                    status_code=init_response.status_code,
                    error="MCP initialize returned an unexpected payload.",
                )

            session_id = init_response.headers.get(SESSION_HEADER)
            if session_id:
                headers[SESSION_HEADER] = session_id

            client.post(
                mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            tools_response = client.post(
                mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )
            if tools_response.status_code >= 400:
                return MCPVerifyResult(
                    ok=False,
                    status_code=tools_response.status_code,
                    error="MCP tools/list failed with HTTP " + str(tools_response.status_code) + ".",
                )
            tools_message = _parse_jsonrpc_body(tools_response)
            if tools_message is None or "result" not in tools_message:
                return MCPVerifyResult(
                    ok=False,
                    status_code=tools_response.status_code,
                    error="MCP tools/list returned an unexpected payload.",
                )
            result = tools_message["result"]
            raw_tools = result.get("tools", []) if isinstance(result, dict) else []
            if not isinstance(raw_tools, list):
                raw_tools = []
            tools = [tool.get("name", "") for tool in raw_tools if isinstance(tool, dict)]
            return MCPVerifyResult(ok=True, tools=tools, status_code=tools_response.status_code)
    except httpx.HTTPError as e:
        return MCPVerifyResult(ok=False, error="Could not reach the MCP endpoint: " + str(e))

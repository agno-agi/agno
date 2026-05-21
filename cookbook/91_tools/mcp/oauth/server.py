"""OAuth-protected MCP server (mock for cookbook demonstration).

In production, use FastMCP's OIDCProxy to protect your MCP server with a real
OAuth2 authorization server. This mock validates a static bearer token so the
cookbook runs without external infrastructure.

Run this first:
    .venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py
"""

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

EXPECTED_TOKEN = "demo-access-token"

mcp = FastMCP("OAuth Protected Server")


@mcp.tool
async def get_secret_data() -> str:
    """Return sensitive data — only accessible with a valid bearer token."""
    request = get_http_request()
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return "Unauthorized: missing bearer token"
    token = auth_header.removeprefix("Bearer ")
    if token != EXPECTED_TOKEN:
        return f"Unauthorized: invalid token '{token}'"
    return "Secret data: the answer is 42"


@mcp.tool
async def ping() -> str:
    """Health check tool."""
    return "pong"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000)

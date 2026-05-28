"""
Server
=============================

Demonstrates server.
"""

from fastmcp import FastMCP
from fastmcp.server import Context
from fastmcp.server.dependencies import get_http_request

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


mcp = FastMCP("My Server")


@mcp.tool
async def greet(name: str, ctx: Context) -> str:
    """Greet a user with personalized information from headers."""
    # Get the HTTP request object
    request = get_http_request()

    # Access headers (lowercase!)
    user_id = request.headers.get("x-user-id", "unknown")
    tenant_id = request.headers.get("x-tenant-id", "unknown")
    agent_name = request.headers.get("x-agent-name", "unknown")

    print("=" * 60)
    print(f"Headers -> Agent: {agent_name}, User: {user_id}, Tenant: {tenant_id}")
    print("=" * 60)

    return f"Hello, {name}! (User: {user_id}, Tenant: {tenant_id})"


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000)

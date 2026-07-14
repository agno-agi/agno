"""
Simple MCP server that logs headers received from clients.

Run with: python server.py
"""

from fastmcp import FastMCP
from fastmcp.server import Context
from fastmcp.server.dependencies import get_http_request

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

mcp = FastMCP("Dynamic Headers Demo Server")


@mcp.tool
async def greet(name: str, ctx: Context) -> str:
    """Greet a user with personalized information from headers."""
    request = get_http_request()

    # Access headers (lowercase)
    user_id = request.headers.get("x-user-id", "unknown")
    session_id = request.headers.get("x-session-id", "unknown")
    agent_name = request.headers.get("x-agent-name", "unknown")
    team_name = request.headers.get("x-team-name", "none")

    print("=" * 60)
    print(
        f"Headers -> User: {user_id} | Session: {session_id} | Agent: {agent_name} | Team: {team_name}"
    )
    print("=" * 60)

    return f"Hello, {name}! (User: {user_id}, Agent: {agent_name}, Team: {team_name})"


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000)

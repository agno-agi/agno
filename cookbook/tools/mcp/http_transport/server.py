"""Start an example MCP server that uses the SSE transport."""

import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calendar_assistant")


@mcp.tool()
def get_events(day: str) -> str:
    return f"There are no events scheduled for {day}."


@mcp.tool()
def get_birthdays_this_week() -> str:
    return "It is your mom's birthday tomorrow"


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "sse"
    if transport not in ["sse", "streamable-http"]:
        print("Invalid transport. Must be either 'sse' or 'streamable-http'")
        sys.exit(1)
    mcp.run(transport=transport)

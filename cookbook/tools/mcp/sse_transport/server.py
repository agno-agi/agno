"""Start an example MCP server that uses the SSE transport."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calendar_assistant")


@mcp.tool()
def get_events(day: str) -> str:
    return f"There are no events scheduled for {day}."


@mcp.tool()
def get_birthdays_this_week() -> str:
    return "It is your mom's birthday tomorrow"


if __name__ == "__main__":
    mcp.run(transport="sse")

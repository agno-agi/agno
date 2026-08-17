"""
This example demonstrates how to use multiple MCP servers in a single agent.

Pass one MCPTools instance per server in the agent's tools list.

Prerequisites:
- Set the environment variable "ACCUWEATHER_API_KEY" for the weather MCP tools.
- You can get the API key from the AccuWeather website: https://developer.accuweather.com/
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    # Initialize one MCPTools instance per MCP server
    airbnb_tools = MCPTools(
        "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
        timeout_seconds=30,
    )
    brave_tools = MCPTools(
        "npx -y @modelcontextprotocol/server-brave-search",
        env={
            "BRAVE_API_KEY": getenv("BRAVE_API_KEY"),
        },
        timeout_seconds=30,
    )

    # Connect to the MCP servers
    await airbnb_tools.connect()
    await brave_tools.connect()

    # Use the MCP tools with an Agent
    agent = Agent(
        tools=[airbnb_tools, brave_tools],
        markdown=True,
    )
    await agent.aprint_response(message)

    # Close the MCP connections
    await airbnb_tools.close()
    await brave_tools.close()


# Example usage
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("What listings are available in Barcelona tonight?"))
    asyncio.run(run_agent("What's the fastest way to get to Barcelona from London?"))

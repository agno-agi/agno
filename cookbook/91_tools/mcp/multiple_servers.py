"""
This example demonstrates how to use multiple MCP servers in a single agent.

Each server gets its own MCPTools instance; pass them all to the agent.

Prerequisites:
- Set the environment variable "BRAVE_API_KEY" for the Brave search MCP tools.
- You can get the API key from the Brave website: https://brave.com/search/api/
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    # Initialize one MCPTools instance per server
    airbnb_tools = MCPTools(
        command="npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
        timeout_seconds=30,
    )
    search_tools = MCPTools(
        command="npx -y @modelcontextprotocol/server-brave-search",
        env={"BRAVE_API_KEY": getenv("BRAVE_API_KEY")},
        timeout_seconds=30,
    )

    # Connect to the MCP servers
    await airbnb_tools.connect()
    await search_tools.connect()

    # Use the MCP tools with an Agent
    agent = Agent(
        tools=[airbnb_tools, search_tools],
        markdown=True,
    )
    await agent.aprint_response(message)

    # Close the MCP connections
    await airbnb_tools.close()
    await search_tools.close()


# Example usage
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("What listings are available in Barcelona tonight?"))
    asyncio.run(run_agent("What's the fastest way to get to Barcelona from London?"))

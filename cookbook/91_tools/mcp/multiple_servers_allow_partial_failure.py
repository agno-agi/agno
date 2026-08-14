"""
This example demonstrates how to use multiple MCP servers in a single agent, allowing for partial failure.

This is useful if you are connecting to MCP servers that are not always available or prone to failure,
but don't want to stop the execution if some of the servers fail to connect. With one MCPTools
instance per server, a failed connection is just an exception to catch: skip that server and
hand the agent the toolkits that did connect.

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
    server_tools = [
        MCPTools(
            command="npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
            timeout_seconds=30,
        ),
        MCPTools(
            command="npx -y @modelcontextprotocol/server-brave-search",
            env={"BRAVE_API_KEY": getenv("BRAVE_API_KEY")},
            timeout_seconds=30,
        ),
    ]

    # Connect to each server, skipping the ones that fail
    connected_tools = []
    for tools in server_tools:
        try:
            await tools.connect()
            connected_tools.append(tools)
        except Exception as e:
            print(f"Skipping MCP server that failed to connect: {e}")

    # Use the MCP tools that connected with an Agent
    agent = Agent(
        tools=connected_tools,
        markdown=True,
    )
    await agent.aprint_response(message)

    # Close the MCP connections
    for tools in connected_tools:
        await tools.close()


# Example usage
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("What listings are available in Barcelona tonight?"))
    asyncio.run(run_agent("What's the fastest way to get to Barcelona from London?"))

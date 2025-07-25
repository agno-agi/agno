"""
This example demonstrates how to use multiple MCP servers in a single agent.

Prerequisites:
- Set the environment variable "ACCUWEATHER_API_KEY" for the weather MCP tools.
- You can get the API key from the AccuWeather website: https://developer.accuweather.com/
"""

import asyncio

from agno.agent import Agent
from agno.tools.mcp import MultiMCPTools


async def run_agent(message: str) -> None:
    # Initialize the MCP server
    mcp_tools = await MultiMCPTools.connect(
        [
            "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
            "npx -y @timlukahorstmann/mcp-weather",
        ],
        timeout_seconds=30,
    )

    # Use the MCP tools with an Agent
    agent = Agent(
        tools=[mcp_tools],
        markdown=True,
        show_tool_calls=True,
    )
    await agent.aprint_response(message)

    # Close the MCP connection
    await mcp_tools.close()


# Example usage
if __name__ == "__main__":
    asyncio.run(run_agent("What listings are available in Barcelona tonight?"))
    asyncio.run(run_agent("Will it be sunny in Barcelona tomorrow?"))

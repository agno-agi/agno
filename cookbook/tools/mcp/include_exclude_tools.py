"""
This example demonstrates how to use multiple MCP servers in a single agent.

Prerequisites:
- Google Maps:
    - Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
    You can obtain the API key from the Google Cloud Console:
    https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

    - You also need to activate the Address Validation API for your .
    https://console.developers.google.com/apis/api/addressvalidation.googleapis.com
"""

import asyncio
import os

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent(message: str) -> None:
    """Run the GitHub agent with the given message."""

    env = {
        **os.environ,
        "GOOGLE_MAPS_API_KEY": os.getenv("GOOGLE_MAPS_API_KEY"),
    }
    # Initialize the MCP server
    time_server_params = StdioServerParameters(
        command="uvx",
        args=["mcp-server-time", "--local-timezone=Europe/London"],
    )

    maps_server_params = StdioServerParameters(
        command="npx", args=["-y", "@modelcontextprotocol/server-google-maps"], env=env
    )

    async with (
        MCPTools(
            server_params=time_server_params, exclude_tools=["convert_time"]
        ) as time_mcp_tools,
        MCPTools(
            server_params=maps_server_params,
            include_tools=["maps_search_places", "maps_place_details"],
        ) as maps_mcp_tools,
    ):
        agent = Agent(
            tools=[time_mcp_tools, maps_mcp_tools],
            markdown=True,
            show_tool_calls=True,
        )

        await agent.aprint_response(message, stream=True)


# Example usage
if __name__ == "__main__":
    # Pull request example
    asyncio.run(
        run_agent(
            "What is the current time in Cape Town? What restaurants are open right now?"
        )
    )

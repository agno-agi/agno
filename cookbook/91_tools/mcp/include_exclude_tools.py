"""
This example demonstrates how to filter the tools exposed by each MCP server.

include_tools and exclude_tools are set per MCPTools instance, so each server gets
its own filter.

Prerequisites:
- Google Maps:
    - Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
    You can obtain the API key from the Google Cloud Console:
    https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

    - You also need to activate the Address Validation API for your .
    https://console.developers.google.com/apis/api/addressvalidation.googleapis.com
"""

import asyncio

from agno.agent import Agent
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    """Run the GitHub agent with the given message.

    Remember to set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
    """

    # Initialize one MCPTools instance per MCP server, each with its own filter
    async with MCPTools(
        "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
        include_tools=["airbnb_search"],
    ) as airbnb_tools:
        async with MCPTools(
            "npx -y @modelcontextprotocol/server-google-maps",
            exclude_tools=["maps_place_details"],
        ) as maps_tools:
            agent = Agent(
                tools=[airbnb_tools, maps_tools],
                markdown=True,
            )

            await agent.aprint_response(message, stream=True)


# Example usage
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "What listings are available in Cape Town for 2 people for 3 nights from 1 to 4 August 2025?"
        )
    )

    asyncio.run(run_agent("What restaurants are open right now in Cape Town?"))

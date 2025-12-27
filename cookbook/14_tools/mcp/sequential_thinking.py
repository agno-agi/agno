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
from textwrap import dedent

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.yfinance import YFinanceTools


async def run_agent(message: str) -> None:
    """Run the GitHub agent with the given message."""

    async with (
        MCPTools(
            command="npx -y @modelcontextprotocol/server-sequential-thinking"
        ) as sequential_thinking_mcp_tools,
    ):
        agent = Agent(
            tools=[
                sequential_thinking_mcp_tools,
                YFinanceTools(),
            ],
            instructions=dedent("""\
                ## Using the think tool
                Before taking any action or responding to the user after receiving tool results, use the think tool as a scratchpad to:
                - List the specific rules that apply to the current request
                - Check if all required information is collected
                - Verify that the planned action complies with all policies
                - Iterate over tool results for correctness

                ## Rules
                - Its expected that you will use the think tool generously to jot down thoughts and ideas.
                - Use tables where possible\
                """),
            markdown=True,
        )

        await agent.aprint_response(message, stream=True)


# Example usage
if __name__ == "__main__":
    # Pull request example
    asyncio.run(run_agent("Write a report comparing NVDA to TSLA"))

"""🏠 MCP Airbnb Agent - Search for Airbnb listings!

This example shows how to create an agent that uses MCP and Gemini 2.5 Pro to search for Airbnb listings.

Run: `pip install google-genai mcp agno` to install the dependencies
"""

import asyncio

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.mcp import MCPTools


async def run_mcp_agent(message: str):
    # Initialize the MCP tools
    mcp_tools = MCPTools("npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt")

    # Connect to the MCP server
    await mcp_tools.connect()

    # Use the MCP tools with an Agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp_tools],
        markdown=True,
    )
    await agent.aprint_response(message)

    # Close the MCP connection
    await mcp_tools.close()


if __name__ == "__main__":
    asyncio.run(run_mcp_agent("Show me listings in Barcelona, for 2 people."))

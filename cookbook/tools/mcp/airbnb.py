"""🏠 MCP Airbnb Agent - Search for Airbnb listings!

This example shows how to create an agent that uses MCP and Gemini 2.5 Pro to search for Airbnb listings.

Run: `pip install google-genai mcp agno` to install the dependencies
"""

import asyncio

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.mcp import MCPTools


async def run_mcp_agent(message: str):
    # Setup the MCP connection
    mcp_tools = await MCPTools.connect("npx -y @timlukahorstmann/mcp-weather")

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
    asyncio.run(run_mcp_agent("Is it sunny in Barcelona?"))

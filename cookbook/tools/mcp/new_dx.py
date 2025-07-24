import asyncio

from agno.agent import Agent
from agno.tools.mcp import MCPTools


async def run_mcp_agent(message: str):
    # Connect to the MCP server
    mcp_tools = await MCPTools.connect("npx -y @openbnb/mcp-server-airbnb")

    # Use MCP
    agent = Agent(tools=[mcp_tools])
    await agent.aprint_response(message, stream=True)

    # Close the MCP connection
    await mcp_tools.close()


if __name__ == "__main__":
    asyncio.run(
        run_mcp_agent(
            "What listings are available in San Francisco for 2 people for 3 nights from 1 to 4 August 2025?"
        )
    )

"""🏠 MCP Airbnb Agent - New DX!

This shows the NEW MCPTools approach - no async context managers needed!
Simple instantiation + explicit connection = much cleaner DX.

Run: `pip install google-genai mcp agno` to install the dependencies
"""

import asyncio

from agno.agent import Agent
from agno.tools.mcp import MCPTools


async def run_mcp_agent():
    mcp_tools = await MCPTools.connect(
        "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"
    )

    try:
        agent = Agent(tools=[mcp_tools])
        await agent.aprint_response(
            "What listings are available in San Francisco for 2 people for 3 nights from 1 to 4 August 2025?",
            stream=True,
        )

    finally:
        await mcp_tools.close()


if __name__ == "__main__":
    asyncio.run(run_mcp_agent())

"""
Show how to connect to MCP servers that use the SSE transport using our MCPTools class.
Check the README.md file for instructions on how to run these examples.

Note: SSE as a standalone transport is deprecated. Prefer Streamable HTTP for new servers.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# This is the URL of the MCP server we want to use.
server_url = "http://localhost:8000/sse"


async def run_agent(message: str) -> None:
    mcp_tools = MCPTools(
        transport="sse",
        url=server_url,
        refresh_connection=True,  # (Optional) Refresh the MCP connection and tools on each run
    )
    await mcp_tools.connect()
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[mcp_tools],
        markdown=True,
    )
    await agent.aprint_response(input=message, stream=True, markdown=True)
    await mcp_tools.close()


# We can connect to multiple MCP servers at once, even if they use different transports.
# In this example we connect to both our example server (SSE transport), and a different server (stdio transport).
async def run_agent_with_multiple_servers(message: str) -> None:
    airbnb_tools = MCPTools(
        command="npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"
    )
    sse_tools = MCPTools(
        transport="sse",
        url=server_url,
        refresh_connection=True,  # (Optional) Refresh the MCP connection and tools on each run
    )
    await airbnb_tools.connect()
    await sse_tools.connect()
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[airbnb_tools, sse_tools],
        markdown=True,
    )
    await agent.aprint_response(input=message, stream=True, markdown=True)
    await airbnb_tools.close()
    await sse_tools.close()


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("Do I have any birthdays this week?"))
    asyncio.run(run_agent("What else is on my calendar this week?"))
    asyncio.run(
        run_agent_with_multiple_servers(
            "Can you check when is my mom's birthday, and if there are any AirBnb listings in SF for two people for that day?"
        )
    )

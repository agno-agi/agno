"""
Show how to connect to MCP servers that use either SSE or Streamable HTTP transport using our MCPTools and MultiMCPTools classes.

Check the README.md file for instructions on how to run these examples.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools, MultiMCPTools

# This is the URL of the MCP server we want to use.
server_url = "http://localhost:8000/mcp"


async def run_agent(message: str) -> None:
    mcp_tools = MCPTools(
        transport="streamable-http",
        url=server_url,
        refresh_connection=True,  # (Optional) Refresh the MCP connection and tools on each run
    )
    await mcp_tools.connect()
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp_tools],
        markdown=True,
    )
    await agent.aprint_response(input=message, stream=True, markdown=True)
    await mcp_tools.close()


# Using MultiMCPTools, we can connect to multiple MCP servers at once, even if they use different transports.
# In this example we connect to both our example server (Streamable HTTP transport), and a different server (stdio transport).
async def run_agent_with_multimcp(message: str) -> None:
    mcp_tools = MultiMCPTools(
        commands=["npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"],
        urls=[server_url],
        urls_transports=["streamable-http"],
        refresh_connection=True,  # (Optional) Refresh the MCP connection and tools on each run
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp_tools],
        markdown=True,
    )
    await agent.aprint_response(input=message, stream=True, markdown=True)


if __name__ == "__main__":
    asyncio.run(run_agent("Do I have any birthdays this week?"))
    asyncio.run(run_agent("What else is on my calendar this week?"))
    asyncio.run(
        run_agent_with_multimcp(
            "Can you check when is my mom's birthday, and if there are any AirBnb listings in SF for two people for that day?",
        )
    )

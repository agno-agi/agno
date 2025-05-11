"""
Show how to connect to MCP servers that use either SSE or Streamable HTTP transport using our MCPTools and MultiMCPTools classes.

Check the README.md file for instructions on how to run these examples.
"""

import asyncio
import sys

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import (
    MCPTools,
    MultiMCPTools,
    SSEClientParams,
    StreamableHTTPClientParams,
)


def get_server_url(transport: str) -> str:
    if transport == "sse":
        return "http://localhost:8000/sse"
    elif transport == "streamable-http":
        return "http://localhost:8000/mcp"
    else:
        raise ValueError(f"Invalid transport: {transport}")


async def run_agent(message: str, transport: str) -> None:
    server_url = get_server_url(transport)
    url = server_url.format(transport=transport)
    async with MCPTools(transport=transport, url=url) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message=message, stream=True, markdown=True)


# Using MultiMCPTools, we can connect to multiple MCP servers at once, even if they use different transports.
# In this example we connect to both our example server (HTTP transport), and a different server (stdio transport).
async def run_agent_with_multimcp(message: str, transport: str) -> None:
    server_url = get_server_url(transport)
    url = server_url.format(transport=transport)
    async with MultiMCPTools(
        commands=["npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"],
        urls=[url],
        urls_transport=[transport],
    ) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message=message, stream=True, markdown=True)


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "sse"
    if transport not in ["sse", "streamable-http"]:
        print("Invalid transport. Must be either 'sse' or 'streamable-http'")
        sys.exit(1)

    asyncio.run(run_agent("Do I have any birthdays this week?", transport))
    asyncio.run(
        run_agent_with_multimcp(
            "Can you check when is my mom's birthday, and if there are any AirBnb listings in SF for two people for that day?",
            transport,
        )
    )

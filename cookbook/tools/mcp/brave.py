"""MCP Brave Agent - Search for Brave

This example shows how to create an agent that uses Anthropic to search for information using the Brave MCP server.

You can get the Brave API key from https://brave.com/search/api/

Run: `pip install anthropic mcp agno` to install the dependencies
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.utils.pprint import apprint_run_response


async def run_agent(message: str) -> None:
    async with MCPTools(
        "npx -y @modelcontextprotocol/server-brave-search",
        env={
            "BRAVE_API_KEY": getenv("BRAVE_API_KEY"),
        },
    ) as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[mcp_tools],
            markdown=True,
        )

        response_stream = await agent.arun(message)
        await apprint_run_response(response_stream)


if __name__ == "__main__":
    asyncio.run(run_agent("What is the weather in Tokyo?"))

"""MCP Parallel Agent - Search for Parallel

This example shows how to create an agent that uses Parallel to search for information using the Parallel MCP server.

Run: `pip install anthropic mcp agno` to install the dependencies

Prerequisites:
- Set the environment variable "PARALLEL_API_KEY" with your Parallel API key.
- You can get the API key from the Parallel website: https://parallel.ai/

Usage:
  python cookbook/tools/mcp/parallel.py

Example:
  python cookbook/tools/mcp/parallel.py "What is the weather in Tokyo?"
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import StreamableHTTPClientParams
from agno.utils.pprint import apprint_run_response

server_params = StreamableHTTPClientParams(
    url="https://search-mcp.parallel.ai/mcp",
    headers={
        "authorization": f"Bearer {getenv('PARALLEL_API_KEY')}",
    },
)


async def run_agent(message: str) -> None:
    async with MCPTools(
        transport="streamable-http", server_params=server_params
    ) as parallel_mcp_server:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[parallel_mcp_server],
            markdown=True,
        )
        response_stream = await agent.arun(message)
        await apprint_run_response(response_stream)


if __name__ == "__main__":
    asyncio.run(run_agent("What is the weather in Tokyo?"))

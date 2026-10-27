"""
Bowmark MCP Agent
=================

Give an Agno agent typed functions for live websites through Bowmark's remote MCP server.
The agent calls `get_library` to find functions for a site, then `run` to execute a short
script against them and get structured results back.

Setup:
- Get a Bowmark API key at https://bowmark.ai (the first $10 of runs each month is free)
- export BOWMARK_API_KEY=***
"""

import asyncio
from datetime import timedelta
from os import getenv

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import StreamableHTTPClientParams


async def run_agent(message: str) -> None:
    server_params = StreamableHTTPClientParams(
        url="https://api.bowmark.ai/mcp",
        headers={"Authorization": f"Bearer {getenv('BOWMARK_API_KEY')}"},
        timeout=timedelta(seconds=300),
    )

    async with MCPTools(
        transport="streamable-http",
        server_params=server_params,
        include_tools=["get_library", "run"],
        timeout_seconds=300,
    ) as bowmark:
        agent = Agent(
            model=Claude(id="claude-sonnet-5-5"),
            tools=[bowmark],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "What are the top 3 stories on Hacker News right now, with their points?"
        )
    )

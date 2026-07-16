"""Parallel MCP Agent - Web Search via Parallel MCP

This example demonstrates how to create an Agno agent that performs web searches using Parallel's MCP server.

Setup:
1. Install Python dependencies:
   ```bash
   uv pip install agno mcp anthropic
   ```

2. Set ANTHROPIC_API_KEY environment variable (required for Claude model).

3. Optionally set PARALLEL_API_KEY — keyless access is rate-limited, setting a key raises the ceiling.

Parallel MCP Docs: https://docs.parallel.ai/integrations/mcp/search-mcp
"""

import asyncio
from datetime import timedelta
from os import getenv

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import StreamableHTTPClientParams

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    """
    Sets up the Parallel MCP server and runs the agent with the given message.
    """
    # Build headers — only add auth if key is present
    headers: dict[str, str] = {}
    api_key = getenv("PARALLEL_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    server_params = StreamableHTTPClientParams(
        url="https://search.parallel.ai/mcp",
        headers=headers,
        timeout=timedelta(seconds=300),
    )

    async with MCPTools(
        transport="streamable-http",
        server_params=server_params,
        include_tools=["web_search", "web_fetch"],
        timeout_seconds=300,
    ) as parallel_mcp_server:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[parallel_mcp_server],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("What is the weather in Tokyo?"))

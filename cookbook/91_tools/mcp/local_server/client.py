"""
Client
=============================

Demonstrates client.
"""

import asyncio

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    # Initialize the MCP server
    async with (
        MCPTools(
            "fastmcp run cookbook/90_tools/mcp/local_server/server.py",  # Supply the command to run the MCP server
        ) as mcp_tools,
    ):
        agent = Agent(
            model=Groq(id="openai/gpt-oss-120b"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# Example usage
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("What is the weather in San Francisco?"))

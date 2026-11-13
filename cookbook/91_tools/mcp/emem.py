"""MCP emem Agent - Shared Memory for AI Agents Working in the Real World

emem is shared memory for AI agents working together in the real world. One
agent writes down what it observed. Another agent reads the same bytes, not a
summary of them. Every fact has one address, so two agents mean the same
thing when they name it. Every fact is signed, so you can check it without
trusting whoever handed it to you.

No API key or account is required for reads.

Example prompts to try:
- "Has this place flooded historically?"
- "What's the air quality at this place right now?"
- "Is this neighbourhood hot for an urban area?"
- "How similar are two places?"
- "Has this place lost forest?"

Run: `uv pip install agno mcp openai` to install the dependencies
"""

import asyncio

from agno.agent import Agent
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

server_url = "https://emem.dev/mcp"


async def run_agent(message: str) -> None:
    async with MCPTools(transport="streamable-http", url=server_url) as mcp_tools:
        agent = Agent(
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True, markdown=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("Has this place flooded historically? Mumbai, India."))

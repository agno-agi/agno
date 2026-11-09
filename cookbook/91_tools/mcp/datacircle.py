"""Datacircle MCP Agent - Find the Best GTM APIs

Connect an Agno agent to Datacircle's hosted MCP server. It needs no API key and
is read-only: it lists the GTM APIs Datacircle benchmarks and searches their plans.

Setup:
1. Install dependencies: `uv pip install "agno[mcp,openai]"`
2. Set `OPENAI_API_KEY` in your environment

Run: `python cookbook/91_tools/mcp/datacircle.py`

Datacircle: https://datacircle.dev
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

DATACIRCLE_MCP_URL = "https://api.datacircle.dev/mcp"


async def run_agent(message: str) -> None:
    async with MCPTools(
        url=DATACIRCLE_MCP_URL, transport="streamable-http"
    ) as datacircle_tools:
        agent = Agent(
            name="DatacircleAgent",
            model=OpenAIResponses(id="gpt-5.6-luna"),
            tools=[datacircle_tools],
            instructions=dedent("""\
                - Use list_apis to see the APIs on the sheet
                - Use search_plans to find plans by API, provider or price
                - Be concise and give the price per 1,000 results for each plan\
            """),
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent("Which APIs find email addresses, and what do they cost?"))

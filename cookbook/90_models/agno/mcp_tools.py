"""
Agno Gateway - hosted tools
===========================

Use tools hosted by Agno through the Gateway MCP endpoint. ``AgnoTools`` handles
the MCP connection and authentication; the agent only selects the tool names it
needs.

Requires:
- AGNO_API_KEY
- The ``mcp`` package (``uv pip install -U mcp``)

Optional:
- AGNO_GATEWAY_MCP_URL to override the default hosted MCP endpoint.
"""

import asyncio

from agno.agent import Agent
from agno.models.agno import Agno
from agno.tools.agno import AgnoTools


async def main() -> None:
    async with AgnoTools(include_tools=["web_search"]) as agno_tools:
        agent = Agent(
            model=Agno(id="openai/gpt-5.4"),
            tools=[agno_tools],
            markdown=True,
        )
        await agent.aprint_response(
            "Use web_search to find the best espresso machines in 2026, then summarize the top picks."
        )


if __name__ == "__main__":
    asyncio.run(main())

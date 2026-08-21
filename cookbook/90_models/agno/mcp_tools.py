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
    async with AgnoTools(include_tools=["you_search"]) as agno_tools:
        agent = Agent(
            model=Agno(id="openai/gpt-5.4"),
            tools=[agno_tools],
            markdown=True,
            debug_mode=True,
            debug_level=2,
        )
        await agent.aprint_response(
            "tell me about new agno features."
        )


if __name__ == "__main__":
    asyncio.run(main())

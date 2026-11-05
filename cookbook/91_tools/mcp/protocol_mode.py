"""
MCP Protocol Mode
=============================

Choose which MCP protocol era MCPTools negotiates with the server.

"legacy" (the default) keeps the session-based era (<= 2025-11-25): the
connection is long-lived and is_alive() can report liveness.

"auto" negotiates the newest era both sides support. The 2026-07-28 era is
sessionless -- requests are self-contained, so any replica behind a load
balancer can serve them. Keep "legacy" for a server that gates access on
initialize, holds per-session state, or elicits input mid-tool.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

MCP_URL = "https://docs.agno.com/mcp"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str, protocol_mode: str) -> None:
    async with MCPTools(
        transport="streamable-http", url=MCP_URL, protocol_mode=protocol_mode
    ) as agno_mcp_server:
        print(f"--- protocol_mode={protocol_mode} ---")
        print(f"liveness reported: {await agno_mcp_server.is_alive()}")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=[agno_mcp_server],
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # The default era: a long-lived session, pinged to check it is still there.
    asyncio.run(run_agent("What is an Agno Team?", "legacy"))

    # The newest era the server supports: sessionless, so there is no connection to
    # keep alive and no ping to send.
    asyncio.run(run_agent("What is an Agno Workflow?", "auto"))

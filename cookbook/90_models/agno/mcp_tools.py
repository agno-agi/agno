"""
Agno Gateway - MCP tools
========================

Connect an Agno agent to a Model Context Protocol (MCP) server over Streamable HTTP
and let the model call its tools through the Agno gateway. This example points at a
local MCP server that exposes a ``web_search`` tool.

Requires:
- AGNO_API_KEY as a long-lived ``ag-...`` key (used for both the Agno model and
  MCP auth via ``x-agno-api-key``). Short-lived gateway run JWTs are model-only
  and do not authenticate MCP tools.
- A running MCP server at ``http://localhost:8787/mcp`` (Streamable HTTP) exposing a
  ``web_search`` tool. The search hits live DuckDuckGo, so it needs network access (no
  API key, but it makes a real outbound request).

Set ``AGNO_API_KEY`` in your shell before running (see README), not in this file.
The MCP client reads it automatically; pass ``api_key=...`` to ``MCPTools`` to override.

Install:
    uv pip install -U mcp
"""

import asyncio

from agno.agent import Agent
from agno.models.agno import Agno
from agno.tools.mcp import MCPTools

MCP_URL = "http://localhost:8787/mcp"


async def main():
    # The MCP connection is a context manager: tools are discovered on enter and the
    # session is closed on exit.
    async with MCPTools(url=MCP_URL, transport="streamable-http") as mcp_tools:
        agent = Agent(
            model=Agno(id="openai/gpt-5.4", base_url="http://localhost:8787/v1"),
            
            tools=[mcp_tools],
            markdown=True,
            debug_mode=True
        )
        await agent.aprint_response(
            "Use the web_search tool to find the best espresso machines in 2026, then summarize the top picks."
        )


if __name__ == "__main__":
    asyncio.run(main())

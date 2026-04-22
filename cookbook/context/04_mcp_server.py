"""
MCP Context Provider (Exa's keyless MCP server)
===============================================

MCPContextProvider wraps a single MCP server as a context provider.
The connection is lazy — `aquery()` connects on first use and builds
sub-agent instructions dynamically from the server's `list_tools()`
response. `aclose()` releases the session.

This cookbook connects to Exa's keyless MCP endpoint, so it runs
without an Exa API key (rate-limited). Passing `EXA_API_KEY` through
the URL would raise the ceiling.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.mcp import MCPContextProvider
from agno.models.openai import OpenAIResponses


async def main() -> None:
    # -------------------------------------------------------------------
    # Create the provider (lazy connect)
    # -------------------------------------------------------------------
    exa_mcp = MCPContextProvider(
        server_name="exa",
        transport="streamable-http",
        url="https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa",
    )

    try:
        # -------------------------------------------------------------------
        # Live probe — astatus() forces a connect and reports how many
        # tools the server advertises.
        # -------------------------------------------------------------------
        print(f"astatus() = {await exa_mcp.astatus()}")

        # -------------------------------------------------------------------
        # Create the Agent — one `query_mcp_exa` tool on the caller
        # -------------------------------------------------------------------
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            tools=exa_mcp.get_tools(),
            instructions=exa_mcp.instructions(),
            markdown=True,
        )

        prompt = "Who is the current CEO of Anthropic? Cite a URL."
        print(f"\n> {prompt}\n")
        await agent.aprint_response(prompt)
    finally:
        # MCP sessions need explicit teardown so the async context
        # manager inside MCPTools unwinds cleanly.
        await exa_mcp.aclose()


if __name__ == "__main__":
    asyncio.run(main())

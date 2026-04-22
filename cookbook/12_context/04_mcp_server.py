"""
MCP Context Provider
====================

MCPContextProvider wraps a single MCP server as a context provider.
Instructions for the sub-agent are built dynamically from the
server's `list_tools()` response at connect time, so the calling
agent never sees stale tool docs.

Lifecycle — `asetup` / `aclose` are called explicitly in this
cookbook. In a real app they'd usually run from the framework's
lifespan hook (FastAPI startup/shutdown, etc.) so every registered
provider gets set up and torn down on the same task that owns the
session. That task-ownership matters: the `mcp` SDK uses anyio
cancel scopes internally, and they must exit on the task that
entered them.

This cookbook uses `mode=ContextMode.tools` so the MCP server's
tools land flat on the calling agent. Default mode (`mode=default`)
instead wraps them in a `query_mcp_<id>` sub-agent tool — use that
when composing multiple MCP servers on one caller to avoid tool-name
collisions.

Requires:
    OPENAI_API_KEY
    uvx  (the MCP time server is invoked via `uvx mcp-server-time`;
         any stdio MCP command works)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context import ContextMode
from agno.context.mcp import MCPContextProvider
from agno.models.openai import OpenAIResponses


async def main() -> None:
    # ------------------------------------------------------------------
    # Create the provider (unconnected)
    # ------------------------------------------------------------------
    provider = MCPContextProvider(
        server_name="time",
        transport="stdio",
        command="uvx",
        args=["mcp-server-time"],
        mode=ContextMode.tools,
        model=OpenAIResponses(id="gpt-5.4-mini"),
    )

    # ------------------------------------------------------------------
    # Bracket with asetup / aclose so the MCP session lives on this
    # task. Multiple calls to asetup() are safe.
    # ------------------------------------------------------------------
    await provider.asetup()
    try:
        print(f"astatus() = {await provider.astatus()}\n")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.4"),
            tools=provider.get_tools(),
            instructions=provider.instructions(),
            markdown=True,
        )

        prompt = "What time is it in Tokyo right now?"
        print(f"> {prompt}\n")
        await agent.aprint_response(prompt)
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())

"""
Web Context Provider with Parallel's MCP endpoint
=================================================

`ParallelMCPBackend` speaks to Parallel's public MCP server at
https://search.parallel.ai/mcp — keyless by default (rate-limited),
Bearer-authenticated if `PARALLEL_API_KEY` is set.

Pairs with `ParallelBackend` (direct SDK) but is NOT equivalent: the
SDK exposes `web_search` + `web_extract`, whereas the MCP server
exposes `web_search` + `web_fetch` (token-efficient markdown). Pick
MCP when you want the compressed markdown output, SDK when you need
the raw extraction payload.

Because the backend holds an MCP session, the cookbook explicitly
brackets usage with `asetup()` / `aclose()`. In a real app those
would normally be wired into the framework's lifespan hook.

Requires:
    OPENAI_API_KEY
    (optional) PARALLEL_API_KEY raises the rate ceiling
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.web import ParallelMCPBackend, WebContextProvider
from agno.models.openai import OpenAIResponses


async def main() -> None:
    # ------------------------------------------------------------------
    # Create the provider (unconnected)
    # ------------------------------------------------------------------
    web = WebContextProvider(
        backend=ParallelMCPBackend(),  # reads PARALLEL_API_KEY if present; works keyless otherwise
        model=OpenAIResponses(id="gpt-5.4"),
    )

    # ------------------------------------------------------------------
    # Bracket with asetup / aclose so the MCP session lives on this task
    # ------------------------------------------------------------------
    await web.asetup()
    try:
        print(f"\nweb.status() = {web.status()}\n")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.4"),
            tools=web.get_tools(),
            instructions=web.instructions(),
            markdown=True,
        )

        prompt = "What is the latest stable release of Agno? Cite the source."
        await agent.aprint_response(prompt)
    finally:
        await web.aclose()


if __name__ == "__main__":
    asyncio.run(main())

"""
Web Context Provider with Exa's keyless MCP endpoint
====================================================

`ExaMCPBackend` speaks to Exa's public MCP server at
https://mcp.exa.ai/mcp — keyless by default (rate-limited), keyed if
`EXA_API_KEY` is set.

Good first step for trying out web research with no signup. For
higher throughput or once you have a key, prefer `ExaBackend` (direct
SDK) in `02_web_exa.py`.

Because the backend holds an MCP session, the cookbook explicitly
brackets usage with `asetup()` / `aclose()`. In a real app those
would normally be wired into the framework's lifespan hook.

Requires:
    OPENAI_API_KEY
    (optional) EXA_API_KEY   raises the rate ceiling
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.web import ExaMCPBackend, WebContextProvider
from agno.models.openai import OpenAIResponses


async def main() -> None:
    # ------------------------------------------------------------------
    # Create the provider (unconnected)
    # ------------------------------------------------------------------
    web = WebContextProvider(
        backend=ExaMCPBackend(),  # reads EXA_API_KEY if present; works keyless otherwise
        model=OpenAIResponses(id="gpt-5.4-mini"),
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
            instructions=web.instructions() + "\nAlways cite URLs inline.",
            markdown=True,
        )

        prompt = "What is the latest stable release of CPython? Cite the source."
        print(f"> {prompt}\n")
        await agent.aprint_response(prompt)
    finally:
        await web.aclose()


if __name__ == "__main__":
    asyncio.run(main())

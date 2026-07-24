"""
Basic A2A Client
================

The minimal way to call a remote A2A 1.0 agent from Agno: `A2AClient`.
One toolkit instance binds one remote agent — it resolves the AgentCard,
opens an official `a2a-sdk` client and consumes the response stream for you.

Start `server.py` in another terminal first, then run this script.
"""

import asyncio

from agno.tools.a2a import A2AClient

AGENT_URL = "http://localhost:9999/a2a/agents/basic-agent"


async def main() -> None:
    # `async with` resolves the card, opens one connection and reuses it for
    # every call. Give the toolkit to an Agent via `tools=[...]` to let an LLM
    # drive these same calls (see cookbook/91_tools/a2a/).
    async with A2AClient(url=AGENT_URL) as remote_agent:
        print("Agent card:")
        print(await remote_agent.aget_agent_card())
        print()
        print("Response:")
        print(
            await remote_agent.asend_message(
                message="Introduce yourself in one sentence."
            )
        )


if __name__ == "__main__":
    asyncio.run(main())

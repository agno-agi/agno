"""
Hostinger Router Basic
======================

Cookbook example for Hostinger Router, an OpenAILike model provider.
"""

import asyncio

from agno.agent import Agent
from agno.models.hostinger_router import HostingerRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=HostingerRouter(id="gpt-5-mini"), markdown=True)

# You can also select the provider by string, which resolves to the same class:
# agent = Agent(model="hostinger-router:gpt-5-mini", markdown=True)

# Hostinger Router routes to several vendors, so any model it serves works here:
# HostingerRouter(id="claude-sonnet-5"), HostingerRouter(id="gemini-3.5-flash"),
# or the regional variants such as HostingerRouter(id="claude-sonnet-5-eu").

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Explain quantum computing in simple terms")

    # --- Sync + Streaming ---
    agent.print_response("Explain quantum computing in simple terms", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Explain quantum computing in simple terms"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Explain quantum computing in simple terms", stream=True)
    )

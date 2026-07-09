"""Run `uv pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.orcarouter import OrcaRouter
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Pin a tool-capable model. Note: `orcarouter/auto` may route to a model that does
# not support function calling unless you restrict its pool in the routing console
# (https://www.orcarouter.ai/console/routing).
agent = Agent(
    model=OrcaRouter(id="openai/gpt-4o-mini"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))

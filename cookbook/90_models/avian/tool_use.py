"""Run `uv pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent  # noqa
from agno.models.avian import Avian  # noqa
from agno.tools.websearch import WebSearchTools  # noqa

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Avian(id="deepseek/deepseek-v3.2"),
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
    asyncio.run(agent.aprint_response("What's the latest news about AI?", stream=True))

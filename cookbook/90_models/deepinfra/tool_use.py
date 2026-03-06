"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent  # noqa
from agno.models.deepinfra import DeepInfra  # noqa
from agno.tools.websearch import WebSearchTools  # noqa
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
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

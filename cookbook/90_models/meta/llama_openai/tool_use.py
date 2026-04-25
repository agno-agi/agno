"""Run `uv pip install openai yfinance` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.meta import LlamaOpenAI
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[YFinanceTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats the price of AAPL stock?")

    # --- Sync + Streaming ---
    agent.print_response("Whats the price of AAPL stock?", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Whats the price of AAPL stock?"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats the price of AAPL stock?", stream=True))

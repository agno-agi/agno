"""Run `pip install openai yfinance` to install dependencies."""

# Note: Currently, Llama API does not support tools with parameters other than string.
# This is a limitation of the Llama API.

import asyncio

from agno.agent import Agent
from agno.models.meta import LlamaOpenAI
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[YFinanceTools()],
    show_tool_calls=True,
)
asyncio.run(agent.aprint_response("Whats the price of AAPL stock?", stream=True))

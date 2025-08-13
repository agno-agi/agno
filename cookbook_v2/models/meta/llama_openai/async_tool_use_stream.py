"""Run `pip install openai yfinance` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.meta import LlamaOpenAI
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[YFinanceTools()],
)
asyncio.run(agent.aprint_response("Whats the price of AAPL stock?", stream=True))

"""Run `pip install agno llama-api-client yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.meta import Llama
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[YFinanceTools()],
)
agent.print_response("What is the price of AAPL stock?")

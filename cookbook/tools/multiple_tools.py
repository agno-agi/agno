"""Run `pip install openai ddgs yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), YFinanceTools()],
    instructions=["Use tables to display data"],
    markdown=True,
)
agent.print_response(
    "Write a thorough report on NVDA, get all financial information and latest news",
    stream=True,
)

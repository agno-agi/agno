"""Run `pip install openai duckduckgo-search yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), YFinanceTools(enable_all=True)],
    instructions=["Use tables to display data"],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response(
    "Write a thorough report on NVDA, get all financial information and latest news",
    stream=True,
)

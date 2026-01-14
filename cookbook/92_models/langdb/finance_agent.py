"""Run `pip install yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.langdb import LangDB
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LangDB(id="llama3-1-70b-instruct-v1.0"),
    tools=[YFinanceTools()],
    description="You are an investment analyst that researches stocks and helps users make informed decisions.",
    instructions=["Use tables to display data where possible."],
    markdown=True,
)

# agent.print_response("Share the NVDA stock price and analyst recommendations", stream=True)
agent.print_response("Summarize fundamentals for TSLA", stream=True)

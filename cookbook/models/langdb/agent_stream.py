"""Run `pip install yfinance` to install dependencies."""

from typing import Iterator  # noqa
from agno.agent import Agent, RunOutput  # noqa
from agno.models.langdb import LangDB
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LangDB(id="gemini-1.5-pro-latest"),
    tools=[YFinanceTools()],
    instructions=["Use tables where possible."],
    markdown=True,
)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("What is the stock price of NVDA and TSLA", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("What is the stock price of NVDA and TSLA", stream=True)

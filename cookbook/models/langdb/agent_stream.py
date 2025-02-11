"""Run `pip install yfinance` to install dependencies."""

from typing import Iterator  # noqa
from agno.agent import Agent, RunResponse  # noqa
from agno.models.langdb import LangDB
from agno.tools.yfinance import YFinanceTools

# Option 1: Get project_id from LANGDB_PROJECT_ID environment variable
agent = Agent(
    model=LangDB(id="gemini-1.5-pro-latest"),  # project_id will be read from env
    tools=[YFinanceTools(stock_price=True)],
    instructions=["Use tables where possible."],
    markdown=True,
    show_tool_calls=True,
)

# Option 2: Pass project_id directly
# agent = Agent(
#     model=LangDB(
#         id="gemini-1.5-pro-latest",
#         project_id="your-langdb-project-id"  # This will override env var if set
#     ),
#     tools=[YFinanceTools(stock_price=True)],
#     instructions=["Use tables where possible."],
#     markdown=True,
#     show_tool_calls=True,
# )

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("What is the stock price of NVDA and TSLA", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("What is the stock price of NVDA and TSLA", stream=True)

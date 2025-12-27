"""Run `pip install yfinance` to install dependencies."""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.langdb import LangDB
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=LangDB(id="gpt-4o"),
    tools=[YFinanceTools()],
    instructions=["Use tables where possible."],
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("What is the stock price of NVDA and TSLA")
# print(run.content)

# Print the response in the terminal
agent.print_response("What is the stock price of NVDA and TSLA")

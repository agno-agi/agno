"""Run `pip install yfinance` to install dependencies."""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    tools=[
        YFinanceTools()
    ],
    add_history_to_messages=True,
    num_history_responses=5,
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("What is the price of TSLA?", stream=True)

agent.print_response("What is the price of NVDA?", stream=True)

agent.print_response("What did I ask so far?", stream=True)

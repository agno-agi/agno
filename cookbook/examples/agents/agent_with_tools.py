from agno.agent import Agent
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model="anthropic:claude-3-7-sonnet-latest",
    tools=[YFinanceTools()],
    markdown=True,
)
agent.print_response("What is the stock price of Apple?", stream=True)

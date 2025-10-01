from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("What is the latest price about BTCUSDT on Binance?")

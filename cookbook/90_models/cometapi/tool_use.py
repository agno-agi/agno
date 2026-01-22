from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("What is the latest price about BTCUSDT on Binance?")

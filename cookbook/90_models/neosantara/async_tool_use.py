import asyncio

from agno.agent import Agent
from agno.models.neosantara import Neosantara
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Neosantara(id="grok-4.1-fast-non-reasoning"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Print the response in the terminal
asyncio.run(
    agent.aprint_response("What is the current stock price of NVDA?", stream=True)
)

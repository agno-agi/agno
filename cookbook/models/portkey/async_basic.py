import asyncio

from agno.agent import Agent
from agno.models.portkey import Portkey

agent = Agent(
    model=Portkey(id="@first-integrati-707071/gpt-5-nano"),
    markdown=True,
)

# Print the response in the terminal
asyncio.run(
    agent.aprint_response("What is Portkey and why would I use it as an AI gateway?")
)

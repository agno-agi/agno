import asyncio

from agno.agent import Agent
from agno.models.portkey import Portkey

agent = Agent(
    model=Portkey(id="@first-integrati-707071/gpt-5-nano"),
    description="You help people with their health and fitness goals.",
    instructions=["Recipes should be under 5 ingredients"],
)
# -*- Print a response to the terminal
asyncio.run(
    agent.aprint_response("Share a breakfast recipe.", markdown=True, stream=True)
)

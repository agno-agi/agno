import asyncio

from agno.agent import Agent
from agno.models.neosantara import Neosantara

agent = Agent(
    model=Neosantara(id="grok-4.1-fast-non-reasoning"),
    markdown=True,
)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))

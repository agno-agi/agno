"""
Basic streaming async example using Claude.
"""

import asyncio

from agno.agent.agent import Agent
from agno.models.cohere import Cohere

agent = Agent(
    model=Cohere(id="command-r-08-2024"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))

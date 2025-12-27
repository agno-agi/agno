"""
Basic streaming async example using Nexus.
"""

import asyncio

from agno.agent import Agent
from agno.models.nexus import Nexus

agent = Agent(model=Nexus(id="anthropic/claude-sonnet-4-20250514"), markdown=True)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))

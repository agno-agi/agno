"""
Basic streaming async example using AIMlAPI.
"""

import asyncio

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI

agent = Agent(
    model=AIMLAPI(id="gpt-4o-mini"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))

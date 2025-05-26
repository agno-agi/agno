"""
Basic streaming async example using AIMlAPI.
"""

import asyncio

from agno.agent import Agent
from agno.models.aimlapi import AIMLApi

agent = Agent(
    model=AIMLApi(id="gpt-4o-mini"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))

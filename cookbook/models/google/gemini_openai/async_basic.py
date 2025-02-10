"""
Basic async example using GeminiOpenAI.
"""

import asyncio

from agno.agent.agent import Agent
from agno.models.google import GeminiOpenAI

agent = Agent(
    model=GeminiOpenAI(id="gemini-2.0-flash-exp"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

"""
Async example using Gemini with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-3-pro-preview", thinking_level="low"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats the current news in France?", stream=True))

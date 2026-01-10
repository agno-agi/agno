"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.xai import xAI
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=xAI(id="grok-2"),
    tools=[WebSearchTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
